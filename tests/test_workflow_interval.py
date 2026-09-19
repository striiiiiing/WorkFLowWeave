import asyncio

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
