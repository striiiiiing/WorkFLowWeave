import asyncio
import sqlite3
from datetime import UTC, datetime

import pytest

from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    AnalysisResult,
    AnalysisTask,
    ChannelConfig,
    CollectionResult,
    DeliveryResult,
    ErrorInfo,
    FanInConfig,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)
from logagent.workflow import SQLiteRunStore, WorkflowService


def snapshot(*, channels=True, fan_in=None, tasks=("first", "second"), **options):
    wf = WorkflowDefinition(
        id="demo",
        sources=["source"],
        analyses=[AnalysisTask(id=key, ai="ai", prompt=f"{key}: {{input}}") for key in tasks],
        channels=["one", "two"] if channels else [],
        fan_in=fan_in,
        **options,
    )
    return WorkflowSnapshot(
        workflow=wf,
        sources={"source": SourceConfig(id="source", collector="mock")},
        ai={"ai": AIConfig(id="ai", provider="mock", model="offline")},
        channels={
            key: ChannelConfig(id=key, channel="mock", options={"target": key})
            for key in wf.channels
        },
        created_at=datetime.now(UTC),
    )


class Collector:
    def __init__(self):
        self.calls = []

    async def collect(self, config, context):
        self.calls.append(config.id)
        return CollectionResult(
            source_id=config.id, status="success", text="original data", count=1
        )


class AI:
    def __init__(self, *, fail=(), block=None):
        self.calls = []
        self.fail = set(fail)
        self.block = block
        self.started = asyncio.Event()

    async def execute(self, config, prompt, text, *, task_id, context):
        self.calls.append((task_id, text, config.model))
        if task_id == self.block:
            self.started.set()
            await asyncio.Future()
        if task_id in self.fail:
            return AnalysisResult(
                task_id=task_id,
                status="failed",
                error=ErrorInfo(code="test_failure", message="failure"),
            )
        return AnalysisResult(task_id=task_id, status="success", text=f"{task_id}({text})")


class Channel:
    def __init__(self):
        self.calls = []

    async def send(self, config, notification):
        self.calls.append((notification.output_id, config.id, notification.text))
        return DeliveryResult(
            channel_id=config.id, output_id=notification.output_id, status="success", attempts=1
        )


def service(path, *, ai=None, store_type=SQLiteRunStore):
    c, a, n = Collector(), ai or AI(), Channel()
    store = store_type(path)
    return WorkflowService(c, a, n, run_store=store), store, c, a, n


async def test_full_history_native_checkpoint_and_completed_recovery(tmp_path):
    path = tmp_path / "runs.sqlite3"
    w, store, c, a, n = service(path)
    result = await w.trigger(snapshot(), session_id="run")
    assert result.status == "completed"
    assert result.shared_input == "original data"
    assert [entry[:2] for entry in n.calls] == [
        ("first", "one"),
        ("first", "two"),
        ("second", "one"),
        ("second", "two"),
    ]
    history = await w.history("run", limit=1000)
    completed = [
        entry
        for entry in history
        if entry["event"] == "completed" and "session_id" in entry["payload"]
    ]
    assert [entry["stage"] for entry in completed] == [
        "collect",
        "analyze",
        "aggregate",
        "notify",
        "finish",
    ]
    assert completed[0]["payload"]["shared_input"] == "original data"
    assert completed[1]["payload"]["analyses"][0]["text"] == "first(original data)"
    assert all(entry["created_at"] for entry in history)
    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT count(*) FROM checkpoints WHERE thread_id=?", ("run",)).fetchone()[0]
            >= 5
        )
    store.close()
    new, reopened, c2, a2, n2 = service(path)
    recovered = await new.recover("run")
    assert recovered == result
    assert not c2.calls and not a2.calls and not n2.calls
    assert (await new.get_session("run"))["recoverable"] is False
    reopened.close()


async def test_cancel_resume_reuses_successful_branch_and_original_snapshot(tmp_path):
    path = tmp_path / "runs.sqlite3"
    ai = AI(block="second")
    w, store, c, _, n = service(path, ai=ai)
    snap = snapshot(analysis_concurrency=1)
    task = asyncio.create_task(w.trigger(snap, session_id="run"))
    await asyncio.wait_for(ai.started.wait(), 5)
    assert store.item_results("run", "analyze")["first"]["status"] == "success"
    assert await w.cancel("run")
    cancelled = await asyncio.wait_for(task, 5)
    assert cancelled.status == "cancelled"
    assert w.coordinator.active == 0
    snap.ai["ai"].model = "changed"
    store.close()
    new, reopened, c2, a2, n2 = service(path)
    result = await new.resume("run")
    assert result.status == "completed"
    assert c2.calls == []
    assert a2.calls == [("second", "original data", "offline")]
    assert len(n2.calls) == 4
    reopened.close()


async def test_failed_analysis_recovery_only_retries_failed_branch(tmp_path):
    path = tmp_path / "runs.sqlite3"
    w, store, _, _, n = service(path, ai=AI(fail={"second"}))
    result = await w.trigger(snapshot(analysis_failure="stop"), session_id="run")
    assert result.status == "failed"
    assert not n.calls
    w.ai_service = AI()
    recovered = await w.recover("run")
    assert recovered.status == "completed"
    assert [call[0] for call in w.ai_service.calls] == ["second"]
    failed = await w.history("run", stage="analyze")
    assert any(row["event"] == "failed" for row in failed)
    assert any(row["event"] == "resumed" for row in await w.history("run"))
    store.close()


async def test_completed_stage_survives_checkpoint_failure(tmp_path):
    class FailAfterStage(SQLiteRunStore):
        def save_stage(self, sid, stage, payload, status="completed"):
            super().save_stage(sid, stage, payload, status)
            if stage == "collect":
                raise RuntimeError("simulated exit before LangGraph checkpoint")

    path = tmp_path / "runs.sqlite3"
    w, store, c, a, n = service(path, store_type=FailAfterStage)
    with pytest.raises(LogAgentError, match="checkpoint"):
        await w.trigger(snapshot(), session_id="run")
    assert c.calls == ["source"] and not a.calls and not n.calls
    store.close()
    new, reopened, c2, _, _ = service(path)
    assert (await new.recover("run")).status == "completed"
    assert not c2.calls
    reopened.close()


async def test_send_receipt_crash_does_not_repeat_uncertain_delivery(tmp_path):
    class FailReceipt(SQLiteRunStore):
        def save_delivery(self, sid, receipt):
            if receipt["channel_id"] == "one":
                raise RuntimeError("receipt disk failure")
            return super().save_delivery(sid, receipt)

    path = tmp_path / "runs.sqlite3"
    w, store, _, _, n = service(path, store_type=FailReceipt)
    with pytest.raises(LogAgentError):
        await w.trigger(snapshot(tasks=("first",)), session_id="run")
    assert [row[:2] for row in n.calls] == [("first", "one")]
    store.close()
    new, reopened, c, a, n2 = service(path)
    result = await new.recover("run")
    assert result.status == "partial"
    assert not c.calls and not a.calls
    assert [row[:2] for row in n2.calls] == [("first", "two")]
    assert result.deliveries[0].error.code == "delivery_uncertain"
    assert result.deliveries[0].error.details["delivery_uncertain"] is True
    assert result.deliveries[1].status == "success"
    reopened.close()


async def test_store_failure_before_send_prevents_external_effect(tmp_path):
    class FailIntent(SQLiteRunStore):
        def begin_delivery(self, *args):
            raise RuntimeError("disk unavailable")

    w, store, _, _, channel = service(tmp_path / "runs.sqlite3", store_type=FailIntent)
    with pytest.raises(LogAgentError):
        await w.trigger(snapshot(), session_id="run")
    assert channel.calls == []
    store.close()


async def test_aggregate_failure_is_recoverable_without_repeating_branches(tmp_path):
    path = tmp_path / "runs.sqlite3"
    w, store, _, _, n = service(path, ai=AI(fail={"final"}))
    result = await w.trigger(
        snapshot(fan_in=FanInConfig(ai="ai", order=["second", "$input", "first"])), session_id="run"
    )
    assert result.status == "failed" and result.aggregate.status == "failed"
    assert not result.outputs and not n.calls
    w.ai_service = AI()
    recovered = await w.recover("run")
    assert recovered.status == "completed"
    assert [row[0] for row in w.ai_service.calls] == ["final"]
    assert (
        w.ai_service.calls[0][1] == "second(original data)\n\noriginal data\n\nfirst(original data)"
    )
    store.close()


async def test_duplicate_admission_and_closed_service_recovery(tmp_path):
    path = tmp_path / "runs.sqlite3"
    w, store, _, ai, _ = service(path, ai=AI(block="first"))
    running = asyncio.create_task(w.trigger(snapshot(), session_id="run"))
    await asyncio.wait_for(ai.started.wait(), 5)
    other, second, _, _, _ = service(path)
    with pytest.raises(LogAgentError) as error:
        await other.recover("run")
    assert error.value.code == "session_active"
    assert other.coordinator.active == 0
    await w.shutdown()
    assert (await running).status == "cancelled"
    with pytest.raises(LogAgentError) as closed:
        await w.recover("run")
    assert closed.value.code == "shutdown"
    second.close()
    store.close()


async def test_disabled_channel_and_source_stop_policy(tmp_path):
    w, store, _, _, n = service(tmp_path / "runs.sqlite3")
    snap = snapshot(tasks=("first",))
    snap.channels["one"].enabled = False
    result = await w.trigger(snap, session_id="run")
    assert result.deliveries[0].status == "skipped"
    assert [row[1] for row in n.calls] == ["two"]
    with pytest.raises(LogAgentError) as duplicate:
        await w.trigger(snap, session_id="run")
    assert duplicate.value.code == "session_exists"
    store.close()


def test_recoverable_service_rejects_in_memory_database():
    with pytest.raises(LogAgentError, match="SQLite 文件"):
        WorkflowService(Collector(), AI(), Channel(), database=":memory:")


async def test_recover_reconciles_final_status_after_commit_failure(tmp_path):
    class FailFinalStatus(SQLiteRunStore):
        def set_status(self, sid, status, error=None):
            if status == "completed":
                raise RuntimeError("disk failure after completed result")
            return super().set_status(sid, status, error)

    path = tmp_path / "runs.sqlite3"
    w, store, _, _, _ = service(path, store_type=FailFinalStatus)
    with pytest.raises(LogAgentError):
        await w.trigger(snapshot(), session_id="run")
    assert store.get_session("run")["status"] == "interrupted"
    store.close()
    new, reopened, c, a, n = service(path)
    assert (await new.recover("run")).status == "completed"
    assert (await new.get_session("run"))["status"] == "completed"
    assert not c.calls and not a.calls and not n.calls
    reopened.close()


async def test_recovery_refuses_missing_prerequisite(tmp_path):
    path = tmp_path / "runs.sqlite3"
    w, store, _, _, _ = service(path, ai=AI(fail={"second"}))
    await w.trigger(snapshot(analysis_failure="stop"), session_id="run")
    store.close()
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM run_stages WHERE session_id=? AND stage=?", ("run", "collect"))
    new, reopened, c, a, n = service(path)
    with pytest.raises(LogAgentError) as error:
        await new.recover("run")
    assert error.value.code == "storage_corrupt"
    assert not c.calls and not a.calls and not n.calls
    reopened.close()


async def test_stage_journal_recovers_when_native_checkpoint_is_missing(tmp_path):
    path = tmp_path / "runs.sqlite3"
    w, store, _, _, _ = service(path, ai=AI(fail={"second"}))
    await w.trigger(snapshot(analysis_failure="stop"), session_id="run")
    store.close()
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM checkpoints WHERE thread_id=?", ("run",))
        db.execute("DELETE FROM writes WHERE thread_id=?", ("run",))
    new, reopened, c, a, _ = service(path)
    assert (await new.recover("run")).status == "completed"
    assert not c.calls
    assert [call[0] for call in a.calls] == ["second"]
    reopened.close()


async def test_storage_failure_during_status_update_is_structured(tmp_path):
    class OfflineStore(SQLiteRunStore):
        def set_status(self, *args, **kwargs):
            raise RuntimeError("unavailable with private connection details")

    w, store, c, a, n = service(tmp_path / "runs.sqlite3", store_type=OfflineStore)
    with pytest.raises(LogAgentError) as error:
        await w.trigger(snapshot(), session_id="run")
    assert error.value.code == "checkpoint_failed"
    assert "private" not in str(error.value)
    assert not c.calls and not a.calls and not n.calls
    assert w.coordinator.active == 0
    store.close()


@pytest.mark.parametrize("stage,key", [("collect", "source"), ("analyze", "first")])
async def test_missing_successful_item_cannot_be_replayed(tmp_path, stage, key):
    path = tmp_path / "runs.sqlite3"
    w, store, _, _, _ = service(path, ai=AI(fail={"second"}))
    await w.trigger(snapshot(analysis_failure="stop"), session_id="run")
    store.close()
    with sqlite3.connect(path) as db:
        db.execute(
            "DELETE FROM run_items WHERE session_id=? AND stage=? AND item_key=?",
            ("run", stage, key),
        )
    new, reopened, c, a, n = service(path)
    with pytest.raises(LogAgentError) as error:
        await new.recover("run")
    assert error.value.code == "storage_corrupt"
    assert not c.calls and not a.calls and not n.calls
    reopened.close()
