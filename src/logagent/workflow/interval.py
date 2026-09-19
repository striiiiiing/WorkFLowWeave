"""基于单调时钟的定时触发器，复用 Workflow 运行准入与快照规则。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable

from logagent.errors import LogAgentError
from logagent.models import WorkflowDefinition

logger = logging.getLogger(__name__)


class IntervalTrigger:
    """管理启用的 Workflow 周期计划；错过多个周期时不会集中补跑。"""
    def __init__(self, service, *, clock: Callable[[], float] = time.monotonic):
        """绑定运行服务及可注入时钟，初始化计划和唤醒事件。"""
        self._service, self._clock = service, clock
        self._plans: dict[str, tuple[float, float]] = {}
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.paused = False

    def update(self, workflows: Iterable[WorkflowDefinition]) -> None:
        """用当前启用且设有间隔的定义替换计划，所有截止时间从当前时刻重算。"""
        now = self._clock()
        self._plans = {
            workflow.id: (workflow.interval_seconds, now + workflow.interval_seconds)
            for workflow in workflows
            if workflow.enabled and workflow.interval_seconds is not None
        }
        self._wake.set()

    async def tick(self) -> list[str]:
        """触发已到期计划并返回成功提交的 session ID 列表。

        暂停时不触发；准入前先推进截止时间，拒绝也不会积压补跑。
        已知业务错误记录警告，其他异常向上传播。
        """
        if self.paused:
            return []
        now, sessions = self._clock(), []
        for ident, (interval, deadline) in list(self._plans.items()):
            if now < deadline:
                continue
            self._plans[ident] = (interval, now + interval)
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
            delay = min(
                (max(0.0, due - self._clock()) for _, due in self._plans.values()), default=60.0
            )
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
