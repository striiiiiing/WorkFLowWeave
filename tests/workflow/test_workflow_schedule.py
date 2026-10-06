"""Exercise actual APScheduler dispatch and durable schedule boundaries."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import orjson
import pytest
from apscheduler.events import EVENT_JOB_EXECUTED
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import ValidationError

from workflowweave.config import ResourceStore
from workflowweave.config.migrations import RESOURCE_FORMAT_VERSION
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import WorkflowDefinition
from workflowweave.scheduling import cron_trigger, describe_cron
from workflowweave.workflow.execution.scheduler import WorkflowScheduler, schedule_trigger


def definition(schedule=None, **kwargs):
    return WorkflowDefinition(
        id="demo", sources=["source"],
        analyses=[{"user_prompt": "analyze input", "id": "task", "ai": "ai", "model": "model"}], schedule=schedule, **kwargs,
    )


def store_for(tmp_path, schedule=None):
    path = tmp_path / "resources.json"
    if not path.exists():
        path.write_bytes(orjson.dumps({
            "format_version": RESOURCE_FORMAT_VERSION,
            "sources": {"source": {"id": "source", "call": {
                "kind": "cli", "mode": "argv", "executable": "printf",
                "argv": ["%s", "example"],
            }}},
            "ai": {"ai": {"id": "ai", "provider": "mock", "models": {"model": {}}}},
            "mcp_servers": {}, "channels": {},
            "workflows": {"demo": definition(schedule).model_dump(mode="json")},
        }))
    return ResourceStore(path)


@pytest.mark.parametrize("schedule", [
    {"type": "every", "every_seconds": 0},
    {"type": "every", "every_seconds": float("inf")},
    {"type": "at", "at": "2027-01-01T00:00:00"},
    {"type": "cron", "expression": "0 9 * *"},
    {"type": "cron", "expression": "61 9 * * *"},
    {"type": "cron", "expression": "0 9 * * *", "timezone": "Invalid/Zone"},
    {"type": "cron", "expression": "0 0 30 2 *"},
])
def test_invalid_schedule_is_rejected(schedule):
    with pytest.raises(ValidationError):
        definition(schedule)


@pytest.mark.parametrize("field", ["cron", "interval_seconds", "cron_timezone"])
def test_api_model_rejects_legacy_even_when_null(field):
    with pytest.raises(ValidationError):
        definition(**{field: None})


def test_cron_timezone_and_descriptor_share_apscheduler_weekdays(monkeypatch):
    monkeypatch.setattr("apscheduler.triggers.cron.get_localzone", lambda: ZoneInfo("Asia/Tokyo"))
    assert str(cron_trigger("0 9 * * *").timezone) == "Asia/Tokyo"
    trigger = cron_trigger("0 9 * * 0-4", "Asia/Shanghai")
    assert trigger.get_next_fire_time(None, datetime(2026, 9, 27, tzinfo=UTC)) == datetime(
        2026, 9, 28, 1, tzinfo=UTC,
    )
    assert "星期一" in describe_cron("0 9 * * 0", cron_trigger("0 9 * * 0"))
    assert "星期日" in describe_cron("0 9 * * 6", cron_trigger("0 9 * * 6"))
    weekdays = describe_cron("0 9 * * MON-FRI", cron_trigger("0 9 * * MON-FRI"))
    assert "星期一" in weekdays and "星期五" in weekdays
    assert "Monday" not in weekdays and "Friday" not in weekdays


def test_at_rounds_up_and_has_only_one_occurrence():
    at = datetime(2027, 1, 2, 3, 4, 5, 123, tzinfo=UTC)
    trigger = schedule_trigger(definition({"type": "at", "at": at}).schedule)
    assert isinstance(trigger, CronTrigger)
    due = trigger.get_next_fire_time(None, at - timedelta(seconds=1))
    assert due == at.replace(microsecond=0) + timedelta(seconds=1)
    assert trigger.get_next_fire_time(due, due) is None


async def dispatch_once(scheduler, ident):
    completed = asyncio.Event()
    scheduler.scheduler.add_listener(lambda event: completed.set(), EVENT_JOB_EXECUTED)
    scheduler.scheduler.modify_job(ident, next_run_time=datetime.now(UTC) - timedelta(seconds=95))
    scheduler.paused = False
    await asyncio.wait_for(completed.wait(), 2)


async def test_one_scheduler_coalesces_backlog_and_preserves_unchanged_deadlines(tmp_path):
    store = store_for(tmp_path, {"type": "every", "every_seconds": 10})
    service = AsyncMock()
    scheduler = WorkflowScheduler(service, store)
    scheduler.paused = True
    scheduler.update(store.list("workflows"))
    scheduler.start()
    try:
        job = scheduler.scheduler.get_job("demo")
        assert isinstance(job.trigger, IntervalTrigger)
        due = job.next_run_time
        store.save("workflows", definition({"type": "every", "every_seconds": 10}, name="changed"))
        scheduler.update(store.list("workflows"))
        assert scheduler.scheduler.get_job("demo").next_run_time == due
        before = datetime.now(UTC)
        await dispatch_once(scheduler, "demo")
        service.trigger.assert_awaited_once_with("demo")
        assert scheduler.scheduler.get_job("demo").next_run_time >= before + timedelta(seconds=10)
        scheduler.update([definition({"type": "every", "every_seconds": 10}, enabled=False)])
        assert scheduler.scheduler.get_jobs() == []
        scheduler.update(store.list("workflows"))
        assert scheduler.scheduler.get_job("demo").next_run_time > datetime.now(UTC)
        scheduler.update([
            definition({"type": "at", "at": datetime.now(UTC) + timedelta(days=1)}),
            definition({"type": "cron", "expression": "0 9 * * *"}).model_copy(update={"id": "cron"}),
            definition({"type": "every", "every_seconds": 0.25}).model_copy(update={"id": "every"}),
        ])
        assert len(scheduler.scheduler.get_jobs()) == 3
        assert all(job._scheduler is scheduler.scheduler for job in scheduler.scheduler.get_jobs())
    finally:
        await scheduler.stop()
        await scheduler.stop()
    assert not scheduler.scheduler.running


async def test_due_at_is_consumed_before_rejection_and_not_replayed_on_restart(tmp_path, caplog):
    plan = {"type": "at", "at": datetime.now(UTC) - timedelta(seconds=1)}
    store = store_for(tmp_path, plan)

    async def reject(ident):
        assert ResourceStore(store.location).get("workflows", ident).schedule is None
        raise WorkFLowWeaveError("capacity_exhausted", "full")

    service = AsyncMock()
    service.trigger.side_effect = reject
    scheduler = WorkflowScheduler(service, store)
    scheduler.paused = True
    scheduler.update(store.list("workflows"))
    scheduler.start()
    try:
        await dispatch_once(scheduler, "demo")
        service.trigger.assert_awaited_once_with("demo")
        assert "capacity_exhausted" in caplog.text
        assert store.get("workflows", "demo").schedule is None
        assert "demo" not in scheduler._plans
        store.save("workflows", definition(plan))
        scheduler.update(store.list("workflows"))
        assert scheduler.scheduler.get_job("demo") is not None
        assert store.consume_schedule("demo", definition(plan).schedule)
    finally:
        await scheduler.stop()
    restarted = WorkflowScheduler(service, store_for(tmp_path))
    restarted.update(restarted._resources.list("workflows"))
    assert restarted.scheduler.get_jobs() == []


async def test_replaced_deleted_or_disabled_plan_never_submits_stale_callback(tmp_path):
    store = store_for(tmp_path, {"type": "at", "at": datetime(2027, 1, 1, tzinfo=UTC)})
    old = store.get("workflows", "demo").schedule
    service = AsyncMock()
    scheduler = WorkflowScheduler(service, store)
    new = definition({"type": "every", "every_seconds": 60})
    store.save("workflows", new)
    assert await scheduler._execute("demo", old) is None
    assert store.get("workflows", "demo").schedule == new.schedule
    store.save("workflows", new.model_copy(update={"enabled": False}))
    assert await scheduler._execute("demo", new.schedule) is None
    store.delete("workflows", "demo")
    assert await scheduler._execute("demo", old) is None
    service.trigger.assert_not_called()


async def test_at_storage_failure_prevents_trigger(tmp_path, monkeypatch, caplog):
    store = store_for(tmp_path, {"type": "at", "at": datetime(2027, 1, 1, tzinfo=UTC)})
    schedule = store.get("workflows", "demo").schedule
    service = AsyncMock()
    scheduler = WorkflowScheduler(service, store)
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr("workflowweave.config.store.os.replace", fail)
    assert await scheduler._execute("demo", schedule) is None
    assert "storage_failed" in caplog.text
    assert store.get("workflows", "demo").schedule == schedule
    service.trigger.assert_not_called()
