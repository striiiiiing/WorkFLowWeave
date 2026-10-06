"""One in-memory APScheduler, rebuilt from the authoritative Workflow resources."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from apscheduler.events import EVENT_SCHEDULER_SHUTDOWN
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import (
    AtSchedule,
    CronSchedule,
    EverySchedule,
    WorkflowDefinition,
    WorkflowSchedule,
)
from workflowweave.protocols import ResourceStore
from workflowweave.scheduling import cron_trigger

logger = logging.getLogger(__name__)


def schedule_trigger(schedule: WorkflowSchedule):
    if isinstance(schedule, AtSchedule):
        # Cron has second precision: round up so subsecond input never fires early.
        at = schedule.at
        if at.microsecond:
            at = at.replace(microsecond=0) + timedelta(seconds=1)
        return CronTrigger(
            year=at.year,
            month=at.month,
            day=at.day,
            hour=at.hour,
            minute=at.minute,
            second=at.second,
            timezone=at.tzinfo,
        )
    if isinstance(schedule, CronSchedule):
        return cron_trigger(schedule.expression, schedule.timezone)
    return IntervalTrigger(seconds=schedule.every_seconds)


class WorkflowScheduler:
    def __init__(self, service, resources: ResourceStore):
        self._service, self._resources = service, resources
        self.scheduler = AsyncIOScheduler(
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": None},
        )
        self._plans: dict[str, WorkflowSchedule] = {}
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        if value == self._paused:
            return
        self._paused = value
        if not self.scheduler.running:
            return
        if value:
            self.scheduler.pause()
        else:
            self.update(self._resources.list("workflows"))
            self.scheduler.resume()

    def update(self, workflows: Iterable[WorkflowDefinition]) -> None:
        plans = {
            workflow.id: workflow.schedule
            for workflow in workflows
            if workflow.enabled and workflow.schedule is not None
        }
        for ident in self._plans.keys() - plans.keys():
            if self.scheduler.get_job(ident) is not None:
                self.scheduler.remove_job(ident)
        for ident, schedule in plans.items():
            if self._plans.get(ident) == schedule and self.scheduler.get_job(ident) is not None:
                continue
            trigger = schedule_trigger(schedule)
            options = {}
            if isinstance(schedule, AtSchedule):
                # An unconsumed deadline remains due after downtime or disabling.
                now = datetime.now(UTC)
                options["next_run_time"] = trigger.get_next_fire_time(None, now) or now
            self.scheduler.add_job(
                self._execute,
                trigger,
                id=ident,
                replace_existing=True,
                args=(ident, schedule),
                **options,
            )
        self._plans = plans

    async def _execute(self, ident: str, schedule: WorkflowSchedule) -> str | None:
        if self.paused:
            return None
        try:
            if isinstance(schedule, AtSchedule):
                consumed = await asyncio.to_thread(
                    self._resources.consume_schedule, ident, schedule
                )
                if not consumed:
                    return None
                self.update(self._resources.list("workflows"))
            else:
                workflow = self._resources.get("workflows", ident)
                if workflow is None or not workflow.enabled or workflow.schedule != schedule:
                    return None
            if isinstance(schedule, EverySchedule) and self.scheduler.get_job(ident) is not None:
                self.scheduler.modify_job(
                    ident,
                    next_run_time=datetime.now(UTC) + timedelta(seconds=schedule.every_seconds),
                )
            return await self._service.trigger(ident)
        except WorkFLowWeaveError as exc:
            logger.warning("Scheduled workflow rejected: %s (%s)", ident, exc.code)
            return None

    def start(self) -> None:
        self.scheduler.start(paused=self.paused)

    async def stop(self) -> None:
        if not self.scheduler.running:
            return
        stopped = asyncio.get_running_loop().create_future()

        def on_shutdown(event):
            if not stopped.done():
                stopped.set_result(None)

        self.scheduler.add_listener(on_shutdown, EVENT_SCHEDULER_SHUTDOWN)
        try:
            self.scheduler.shutdown(wait=True)
            await stopped
        finally:
            self.scheduler.remove_listener(on_shutdown)
