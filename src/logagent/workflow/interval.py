"""Cron 与旧秒间隔调度，复用 Workflow 运行准入与快照规则。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from logagent.errors import LogAgentError
from logagent.models import WorkflowDefinition

logger = logging.getLogger(__name__)


class IntervalTrigger:
    """管理启用的 Workflow 周期计划；错过多个周期时不会集中补跑。"""
    def __init__(self, service, *, clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        """绑定运行服务及可注入时钟，初始化计划和唤醒事件。"""
        self._service, self._clock = service, clock
        self._wall_clock = wall_clock
        self._plans: dict[str, tuple[float, float]] = {}
        self._cron_plans: dict[str, tuple[str, str, float]] = {}
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.paused = False

    def update(self, workflows: Iterable[WorkflowDefinition]) -> None:
        """保持未变计划的截止时间，避免其他资源更新反复推迟定时运行。"""
        now = self._clock()
        definitions = [workflow for workflow in workflows if workflow.enabled]
        self._plans = {
            workflow.id: self._plans[workflow.id]
            if workflow.id in self._plans and self._plans[workflow.id][0] == workflow.interval_seconds
            else (workflow.interval_seconds, now + workflow.interval_seconds)
            for workflow in definitions if workflow.interval_seconds is not None
        }
        wall_now = self._wall_clock()
        self._cron_plans = {
            workflow.id: self._cron_plans[workflow.id]
            if workflow.id in self._cron_plans
            and self._cron_plans[workflow.id][:2] == (workflow.cron, workflow.cron_timezone)
            else (workflow.cron, workflow.cron_timezone,
                  self._next_cron(workflow.cron, workflow.cron_timezone, wall_now))
            for workflow in definitions if workflow.cron is not None
        }
        self._wake.set()

    @staticmethod
    def _next_cron(expression: str, timezone: str, now: datetime) -> float:
        if now.tzinfo is None:
            raise ValueError("Workflow wall clock must include a timezone")
        return croniter(expression, now.astimezone(ZoneInfo(timezone))).get_next(datetime).timestamp()

    async def tick(self) -> list[str]:
        """触发已到期计划并返回成功提交的 session ID 列表。

        暂停时不触发；准入前先推进截止时间，拒绝也不会积压补跑。
        已知业务错误记录警告，其他异常向上传播。
        """
        if self.paused:
            return []
        now, sessions = self._clock(), []
        due = []
        for ident, (interval, deadline) in list(self._plans.items()):
            if now < deadline:
                continue
            self._plans[ident] = (interval, now + interval)
            due.append(ident)
        wall_now = self._wall_clock()
        for ident, (expression, timezone, deadline) in list(self._cron_plans.items()):
            if wall_now.timestamp() < deadline:
                continue
            self._cron_plans[ident] = (expression, timezone, self._next_cron(expression, timezone, wall_now))
            due.append(ident)
        for ident in due:
            try:
                sessions.append(await self._service.trigger(ident))
            except LogAgentError as exc:
                logger.warning("Scheduled workflow rejected: %s (%s)", ident, exc.code)
        return sessions

    def start(self) -> None:
        """创建定时循环任务；重复启动明确报错。"""
        if self._task is not None:
            raise RuntimeError("IntervalTrigger is already started")
        self._task = asyncio.create_task(self._run(), name="workflow:intervals")

    async def _run(self) -> None:
        """按最近截止时间等待；更新计划通过事件立即唤醒。

        无计划或暂停时等待上限为 60 秒，这是调度等待值，不是业务超时。
        """
        while True:
            self._wake.clear()
            await self.tick()
            delays = [max(0.0, due - self._clock()) for _, due in self._plans.values()]
            delays.extend(max(0.0, due - self._wall_clock().timestamp())
                          for _, _, due in self._cron_plans.values())
            # Re-evaluate wall-clock changes at least once a minute.
            delay = min([60.0, *delays])
            if self.paused:
                delay = 60.0
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def stop(self) -> None:
        """取消并等待调度任务退出，再清理句柄；不直接取消已提交的 Workflow。"""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
