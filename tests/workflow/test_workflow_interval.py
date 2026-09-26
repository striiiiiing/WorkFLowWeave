"""Workflow 定时间隔触发测试。

注入可控时钟和记录调用的服务，推进 tick 检查通过统一 trigger 触发，
错过时间点不集中补跑；模拟拒绝验证不忙重试，并断言自有后台任务可停止。
不启动真实采集、模型或通知。
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from logagent.errors import LogAgentError
from logagent.models import WorkflowDefinition
from logagent.workflow import IntervalTrigger


def workflow(**kwargs):
    return WorkflowDefinition(
        id="demo", sources=["source"], analyses=[{"id": "task", "ai": "ai", "model": "model"}], **kwargs
    )


async def test_interval_uses_trigger_and_does_not_replay_missed_deadlines():
    now = [0.0]

    class Service:
        def __init__(self):
            self.calls = []

        async def trigger(self, ident):
            self.calls.append(ident)
            return str(len(self.calls))

    service = Service()
    intervals = IntervalTrigger(service, clock=lambda: now[0])
    intervals.update([workflow(interval_seconds=10)])
    assert await intervals.tick() == []
    now[0] = 100
    assert await intervals.tick() == ["1"]
    assert await intervals.tick() == []
    intervals.paused = True
    now[0] = 200
    assert await intervals.tick() == []
    intervals.paused = False
    assert await intervals.tick() == ["2"]
    intervals.update([workflow(enabled=False, interval_seconds=10)])
    now[0] = 300
    assert await intervals.tick() == []
    assert service.calls == ["demo", "demo"]


async def test_interval_rejection_has_no_busy_retry_and_owned_task_stops():
    class Service:
        calls = 0

        async def trigger(self, ident):
            self.calls += 1
            raise LogAgentError("capacity_exhausted", "full")

    now = [0.0]
    service = Service()
    intervals = IntervalTrigger(service, clock=lambda: now[0])
    intervals.update([workflow(interval_seconds=10)])
    now[0] = 20
    assert await intervals.tick() == []
    assert await intervals.tick() == []
    assert service.calls == 1
    intervals.start()
    await asyncio.sleep(0)
    await intervals.stop()
    await intervals.stop()
    assert intervals._task is None


def test_cron_requires_five_fields_valid_zone_and_no_legacy_interval():
    assert workflow(cron="0 9 * * *", cron_timezone="Asia/Shanghai").cron == "0 9 * * *"
    for fields in (
        {"cron": "0 9 * *"},
        {"cron": "61 9 * * *"},
        {"cron": "0 9 * * *", "cron_timezone": "Invalid/Zone"},
        {"cron": "0 9 * * *", "interval_seconds": 60},
    ):
        with pytest.raises(ValidationError):
            workflow(**fields)


async def test_cron_uses_timezone_and_skips_missed_occurrences():
    wall = [datetime(2026, 9, 26, 0, 59, tzinfo=UTC)]

    class Service:
        calls = 0

        async def trigger(self, ident):
            self.calls += 1
            return f"{ident}-{self.calls}"

    service = Service()
    intervals = IntervalTrigger(service, clock=lambda: 0.0, wall_clock=lambda: wall[0])
    config = workflow(cron="0 9 * * *", cron_timezone="Asia/Shanghai")
    intervals.update([config])
    assert await intervals.tick() == []
    # 09:00 Shanghai is 01:00 UTC on this date.
    wall[0] += timedelta(minutes=1)
    assert await intervals.tick() == ["demo-1"]
    assert await intervals.tick() == []
    wall[0] += timedelta(days=3)
    assert await intervals.tick() == ["demo-2"]
    intervals.update([config])
    assert await intervals.tick() == []
