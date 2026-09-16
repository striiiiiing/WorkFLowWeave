"""Owned interval scheduling; missed deadlines produce one future run."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable

from logagent.errors import LogAgentError
from logagent.models import WorkflowDefinition

logger = logging.getLogger(__name__)


class IntervalTrigger:
    def __init__(self, service, *, clock: Callable[[], float] = time.monotonic):
        self._service, self._clock = service, clock
        self._plans: dict[str, tuple[float, float]] = {}
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.paused = False

    def update(self, workflows: Iterable[WorkflowDefinition]) -> None:
        now = self._clock()
        self._plans = {
            workflow.id: (workflow.interval_seconds, now + workflow.interval_seconds)
            for workflow in workflows
            if workflow.enabled and workflow.interval_seconds is not None
        }
        self._wake.set()

    async def tick(self) -> list[str]:
        if self.paused:
            return []
        now, sessions = self._clock(), []
        for ident, (interval, deadline) in list(self._plans.items()):
            if now < deadline:
                continue
            # Advance before admission, including rejected runs. No catch-up burst.
            self._plans[ident] = (interval, now + interval)
            try:
                sessions.append(await self._service.trigger(ident))
            except LogAgentError as exc:
                logger.warning("Scheduled workflow rejected: %s (%s)", ident, exc.code)
        return sessions

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("IntervalTrigger is already started")
        self._task = asyncio.create_task(self._run(), name="workflow:intervals")

    async def _run(self) -> None:
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
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
