"""真实父子图逐项流更新、同源查询及有界观察者。"""

import asyncio

import pytest

from logagent.errors import LogAgentError
from logagent.models import AnalysisResult, DeliveryResult, FanInConfig, WorkflowProgress
from logagent.workflow.stream import ProgressHub, StreamConsumer
from tests.workflow.helpers import AI, Channel, snapshot
from tests.workflow.test_workflow_recovery import close, service


async def next_matching(queue, predicate):
    async with asyncio.timeout(5):
        while True:
            item = await queue.get()
            if predicate(item):
                return item


async def test_fast_items_and_report_are_visible_before_slow_siblings(tmp_path):
    release_analysis, release_send = asyncio.Event(), asyncio.Event()
    slow_send_started = asyncio.Event()

    class SlowAI(AI):
        async def execute(self, config, prompt, text, *, task_id, **kwargs):
            if task_id == "second":
                await release_analysis.wait()
            return AnalysisResult(task_id=task_id, status="success", text=f"report {task_id}")

    class SlowChannel(Channel):
        async def send(self, config, notification):
            if config.id == "two":
                slow_send_started.set()
                await release_send.wait()
            return DeliveryResult(channel_id=config.id, output_id=notification.output_id,
                                  status="success", attempts=1)

    w, store, _, _, _ = service(tmp_path / "runs.sqlite3", ai=SlowAI())
    w.channel_manager = SlowChannel()
    try:
        async with w.progress_hub.subscribe("run") as queue:
            await w.trigger(snapshot(), session_id="run")
            first = await next_matching(queue, lambda e: e.event == "item" and e.item_id == "first")
            before = await w.get_session("run")
            assert first.status == "success" and first.version <= before.version
            items = {p.item_id: p for p in before.progress if p.stage == "analyze"}
            assert items["first"].status == "success" and items["second"].status == "pending"
            assert first.result_ref == items["first"].result_ref
            assert "report first" not in first.model_dump_json()
            release_analysis.set()
            report = await next_matching(queue, lambda e: e.event == "aggregate")
            assert report.status == "success" and report.summary["fan_in"] is False
            content = await w.session_view.get_phase_content("run", "aggregate", version=report.version)
            assert content.content["outputs"] == {"first": "report first", "second": "report second"}
            delivered = await next_matching(queue, lambda e: e.event == "delivery" and e.channel_id == "one")
            await slow_send_started.wait()
            assert delivered.status == "success" and w.coordinator.contains("run")
            record = await w.get_session("run")
            assert record.status == "running"
            assert all(p.status == "pending" for p in record.progress
                       if p.event == "delivery" and p.channel_id == "two")
            release_send.set()
            assert (await w.wait("run")).status == "completed"
            terminal = await next_matching(queue, lambda e: e.event == "lifecycle" and e.status == "completed")
            assert terminal.version <= (await w.get_session("run")).version
    finally:
        release_analysis.set()
        release_send.set()
        await close(w, store)


async def test_duplicate_stream_observation_does_not_write_another_version(tmp_path):
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3")
    try:
        await w.trigger(snapshot(channels=False), session_id="run")
        await w.wait("run")
        before = await w.get_session("run")
        report = next(item for item in before.progress if item.event == "aggregate")
        events = []

        async def publish(event):
            events.append(event)

        consumer = StreamConsumer(store, "run", publish, {("aggregate",): "workflow:aggregate"})
        update = {"aggregate": {"phases": {"aggregate": report.result_ref}}}
        await consumer.consume((), update)
        await consumer.consume((), update)
        await consumer.consume(("notify:any",), {"intent_0_0": {}})
        assert len(events) == 1
        assert (await w.get_session("run")).version == before.version
    finally:
        await close(w, store)


async def test_slow_or_disconnected_observer_does_not_block_other_observers():
    hub = ProgressHub(capacity=1)
    event = WorkflowProgress(session_id="run", event="lifecycle", status="running")
    async with hub.subscribe("run") as slow, hub.subscribe("run") as fast:
        await hub.publish(event)
        assert await fast.get() == event
        await hub.publish(event)
        assert await slow.get() is None
        assert await fast.get() == event
        await hub.publish(event)
        assert await fast.get() == event
    assert not hub.subscribers


async def test_stage_rerun_projection_resets_downstream_and_keeps_fixed_history(tmp_path):
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3")
    try:
        await w.trigger(snapshot(channels=False), session_id="run")
        await w.wait("run")
        before = await w.get_session("run")
        ai = AI(block="first")
        w.ai_service = ai
        await w.resume("run", stage="analyze")
        await ai.started.wait()
        record = await w.get_session("run")
        assert record.execution_epoch != before.execution_epoch
        collected = next(p for p in record.progress if p.stage == "collect")
        assert collected.status == "success" and collected.execution_epoch == record.execution_epoch
        assert next(p for p in record.progress if p.item_id == "first").status == "pending"
        assert next(p for p in record.progress if p.event == "aggregate").result_ref is None
        assert await w.get_session("run", version=before.version) == before
        await w.cancel("run")
        await w.wait("run")
    finally:
        await close(w, store)


async def test_model_fan_in_publishes_one_aggregate_completion(tmp_path):
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3")
    try:
        async with w.progress_hub.subscribe("run") as queue:
            await w.trigger(snapshot(channels=False, fan_in=FanInConfig()), session_id="run")
            await w.wait("run")
            events = []
            while not queue.empty():
                events.append(queue.get_nowait())
            reports = [e for e in events if e.event == "aggregate"]
            assert len(reports) == 1
            assert reports[0].status == "success" and reports[0].summary["fan_in"] is True
    finally:
        await close(w, store)


async def test_missing_committed_reference_interrupts_execution(tmp_path, monkeypatch):
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3")
    consume = StreamConsumer.consume

    async def missing_reference(self, namespace, update):
        if "aggregate" in update:
            update = {"aggregate": {"phases": {"aggregate": "missing"}}}
        await consume(self, namespace, update)

    monkeypatch.setattr(StreamConsumer, "consume", missing_reference)
    try:
        await w.trigger(snapshot(channels=False), session_id="run")
        with pytest.raises(LogAgentError) as error:
            await w.wait("run")
        assert error.value.code == "progress_unavailable"
        assert (await w.get_session("run")).status == "interrupted"
    finally:
        await close(w, store)
