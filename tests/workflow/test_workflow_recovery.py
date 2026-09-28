"""Workflow 原生 checkpoint 与业务存档恢复测试。

注入可控采集/AI/通知替身，使用真实 SQLite 和 WorkflowService，验证阶段
顺序、fan-in、失败策略、取消、容量、关闭和旧快照恢复；在写入与回执边界
注入故障，断言成功步骤不重复，材料缺失或损坏明确拒绝，投递不确定不重发。
"""

import asyncio
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import select

from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    ChannelConfig,
    CollectionResult,
    FanInConfig,
)
from logagent.workflow import SessionStore, WorkflowService
from logagent.workflow.session_models import SessionEntry
from tests.workflow.helpers import AI, Channel, Collector, archived, snapshot


def service(path, *, ai=None, store_type=SessionStore):
    c, a, n = Collector(), ai or AI(), Channel()
    store = store_type(path)
    return WorkflowService(c, a, n, session_store=store), store, c, a, n


async def run(workflow, definition=None, sid="run"):
    await workflow.trigger(definition or snapshot(), session_id=sid)
    return await workflow.wait(sid)


async def close(workflow, store):
    await workflow.shutdown()
    store.close()


async def test_full_history_native_checkpoint_and_completed_recovery(tmp_path):
    path = tmp_path / "runs.sqlite3"
    w, store, c, a, n = service(path)
    result = await run(w)
    assert result.status == "completed" and result.shared_input == "original data\n\nsource: success (1)"
    assert sorted(row[:2] for row in n.calls) == [
        ("first", "one"),
        ("first", "two"),
        ("second", "one"),
        ("second", "two"),
    ]
    assert [e["stage"] for e in await w.history("run") if e["scope"] == "phase"] == [
        "collect",
        "analyze",
        "aggregate",
        "notify",
        "finish",
    ]
    record = await w.get_session("run")
    assert record.status == "completed"
    content = await w.session_view.get_phase_content("run", "collect", version=record.version)
    assert content.content["shared_input"] == "original data\n\nsource: success (1)"
    namespaces = {
        checkpoint.config["configurable"]["checkpoint_ns"]
        async for checkpoint in w._checkpointer.alist(None)
    }
    assert "" in namespaces
    await w._cleanup.queue.join()
    assert not await w._cleanup.storage.completed("run")
    await close(w, store)
    new, reopened, c2, a2, n2 = service(path)
    await new.recover("run")
    assert await new.wait("run") == result
    assert not c2.calls and not a2.calls and not n2.calls
    await close(new, reopened)


async def test_trigger_is_immediately_queryable_and_cancel_works_before_first_step(tmp_path):
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3")
    sid = await w.trigger(snapshot(), session_id="run")
    assert sid == "run" and (await w.get_session(sid)).status == "created"
    assert await w.cancel(sid)
    assert (await w.wait(sid)).status == "cancelled"
    assert (await w.get_session(sid)).status == "cancelled"
    await close(w, store)


async def test_cancel_resume_reuses_successful_branch_and_original_snapshot(tmp_path):
    path = tmp_path / "runs.sqlite3"
    ai = AI(block="second")
    w, store, _, _, _ = service(path, ai=ai)
    snap = snapshot(analysis_concurrency=1)
    await w.trigger(snap, session_id="run")
    await asyncio.wait_for(ai.started.wait(), 5)
    deadline = time.monotonic() + 5
    first = None
    while first is None and time.monotonic() < deadline:
        first = await asyncio.to_thread(archived, store, "run", "analyze:item:first")
        if first is None:
            await asyncio.sleep(0)
    assert first is not None and first["body"]["status"] == "success"
    assert await w.cancel("run")
    assert (await w.wait("run")).status == "cancelled"
    snap.ai["ai"].models = {"changed": {}}
    await close(w, store)
    new, reopened, c, a, n = service(path)
    await new.recover("run")
    result = await new.wait("run")
    assert result.status == "completed"
    assert not c.calls and a.calls == [("second", "original data\n\nsource: success (1)", "offline")]
    assert len(n.calls) == 4
    await close(new, reopened)


async def test_checkpoint_fact_survives_archive_interruption_and_recovery(tmp_path):
    class FailAfterArchive(SessionStore):
        def write(self, sid, key, **kwargs):
            entry = super().write(sid, key, **kwargs)
            if key.startswith("collect:item:source:epoch:"):
                raise RuntimeError("process interruption after archive commit")
            return entry

    path = tmp_path / "runs.sqlite3"
    w, store, c, a, n = service(path, store_type=FailAfterArchive)
    with pytest.raises(LogAgentError):
        await run(w)
    assert c.calls == ["source"]
    await close(w, store)
    new, reopened, c, _, _ = service(path)
    await new.recover("run")
    assert (await new.wait("run")).status == "completed"
    assert not c.calls
    await close(new, reopened)


async def test_send_receipt_archive_failure_reuses_checkpoint_receipt(tmp_path):
    class FailReceipt(SessionStore):
        failed = False
        def write(self, sid, key, **kwargs):
            if key.startswith("delivery:first:one:epoch:") and not self.failed:
                self.failed = True
                raise OperationalError(None, None, RuntimeError("receipt disk failure"))
            return super().write(sid, key, **kwargs)

    path = tmp_path / "runs.sqlite3"
    w, store, _, _, n = service(path, store_type=FailReceipt)
    with pytest.raises(LogAgentError):
        await run(w, snapshot(tasks=("first",)))
    original_deliveries = [row[:2] for row in n.calls]
    assert original_deliveries.count(("first", "one")) == 1
    await close(w, store)
    new, reopened, c, a, n = service(path)
    await new.recover("run")
    result = await new.wait("run")
    assert result.status == "completed" and not c.calls and not a.calls
    assert ("first", "one") not in [row[:2] for row in n.calls]
    assert (original_deliveries + [row[:2] for row in n.calls]).count(("first", "two")) == 1
    assert result.deliveries[0].status == "success"
    assert result.deliveries[1].status == "success"
    await close(new, reopened)


async def test_intent_checkpoint_failure_prevents_send(tmp_path):
    w, store, _, _, channel = service(tmp_path / "runs.sqlite3")
    await w.start()
    put = w._checkpointer.aput
    async def fail_intent(config, checkpoint, metadata, new_versions):
        if checkpoint.get("channel_values", {}).get("intents"):
            raise RuntimeError("intent checkpoint failure")
        return await put(config, checkpoint, metadata, new_versions)
    w._checkpointer.aput = fail_intent
    await w.trigger(snapshot(), session_id="run")
    for _ in range(1000):
        if not w.coordinator.active:
            break
        await asyncio.sleep(0.001)
    with pytest.raises(LogAgentError):
        await w.wait("run")
    assert not channel.calls
    assert (await w.get_session("run")).status == "interrupted"
    await close(w, store)


async def test_missing_checkpoint_is_not_reconstructed_from_business_history(tmp_path):
    path = tmp_path / "runs.sqlite3"
    w, store, _, _, _ = service(path)
    await run(w)
    await w._checkpointer.adelete_thread("run")
    with pytest.raises(LogAgentError) as caught:
        await w.recover("run")
    assert caught.value.code == "checkpoint_missing"
    assert (await w.get_session("run")).status == "completed"
    await close(w, store)


@pytest.mark.parametrize("category", ["snapshot", "collection", "analysis", "final"])
async def test_disabled_archive_does_not_disable_checkpoint_recovery(
    tmp_path, category
):
    from logagent.models import BackupPolicy

    policy = BackupPolicy(**{category: False})
    # Block before outputs freeze to exercise recovery from a cancelled checkpoint.
    ai = AI(block="second") if category in {"collection", "analysis"} else AI()
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3", ai=ai)
    await w.trigger(snapshot(backup=policy, analysis_concurrency=1), session_id="run")
    if ai.block:
        await asyncio.wait_for(ai.started.wait(), 5)
        await w.cancel("run")
    await w.wait("run")
    checkpoints = [item async for item in w._checkpointer.alist(None)]
    assert any("original data" in repr(item.checkpoint) + repr(item.pending_writes)
               for item in checkpoints)
    ai.block = None
    await w.recover("run")
    assert (await w.wait("run")).status == "completed"
    await close(w, store)


async def test_duplicate_capacity_and_shutdown(tmp_path):
    ai = AI(block="first")
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3", ai=ai)
    w.coordinator._max = 1
    await w.trigger(snapshot(), session_id="run")
    await asyncio.wait_for(ai.started.wait(), 5)
    with pytest.raises(LogAgentError, match="同一 session"):
        await w.recover("run")
    with pytest.raises(LogAgentError, match="容量"):
        await w.trigger(snapshot(), session_id="other")
    await w.shutdown()
    assert (await w.wait("run")).status == "cancelled"
    with pytest.raises(LogAgentError, match="关闭"):
        await w.recover("run")
    store.close()


@pytest.mark.parametrize(
    "fan_in", [None, FanInConfig(), FanInConfig(
        ai="ai", model="offline", reuse_from=None, order=["second", "$input", "first"],
    )]
)
async def test_order_fanin_and_disabled_channel(tmp_path, fan_in):
    w, store, _, _, n = service(tmp_path / "runs.sqlite3")
    snap = snapshot(fan_in=fan_in)
    snap.channels["one"].enabled = False
    result = await run(w, snap)
    assert result.status == "completed"
    assert result.deliveries[0].status == "skipped"
    assert all(row[1] == "two" for row in n.calls)
    assert list(result.outputs) == (["first", "second"] if fan_in is None else ["final"])
    await close(w, store)


async def test_layered_prompts_and_ordered_fanin_reuse(tmp_path):
    w, store, _, ai, _ = service(tmp_path / "runs.sqlite3")
    snap = snapshot(
        channels=False,
        fan_in=FanInConfig(
            order=["second", "$input", "first"], reuse_from="second",
            system_prompt="", user_prompt="summary {input}",
        ),
        system_prompt="shared {input}", input_prompt="body: {input}",
    )
    snap.workflow.analyses[0].system_prompt = "first system"
    snap.workflow.analyses[0].input_prompt = None
    snap.workflow.analyses[0].user_prompt = "first instruction"
    snap.ai["ai"].system_prompt = "ignored AI system"
    snap.workflow.analyses[1].ai = "other"
    snap.workflow.analyses[1].model = "other-model"
    snap.workflow.analyses[1].input_prompt = ""
    snap.ai["other"] = AIConfig(
        id="other", provider="mock", system_prompt="ignored other system",
        models={"other-model": {}},
    )
    result = await run(w, snap)
    assert result.status == "completed"
    by_id = {request[0]: request for request in ai.requests}
    assert by_id["first"] == (
        "first", "ai", "body: {input}", "first system", "first instruction"
    )
    assert by_id["second"] == ("second", "other", "", "shared {input}", "")
    assert by_id["final"] == ("final", "other", "body: {input}", "", "summary {input}")
    assert ai.calls[-1] == (
        "final",
        "second(original data\n\nsource: success (1))\n\n"
        "original data\n\nsource: success (1)\n\n"
        "first(original data\n\nsource: success (1))",
        "other-model",
    )
    await close(w, store)


async def test_default_fanin_reuses_first_model_and_declared_order(tmp_path):
    w, store, _, ai, _ = service(tmp_path / "runs.sqlite3")
    snap = snapshot(channels=False, fan_in=FanInConfig(), system_prompt="shared system")
    snap.ai["ai"].system_prompt = "ignored AI system"
    result = await run(w, snap)
    assert result.status == "completed"
    assert ai.requests[-1][3] == "shared system"
    assert ai.calls[-1] == (
        "final",
        "original data\n\nsource: success (1)\n\n"
        "first(original data\n\nsource: success (1))\n\n"
        "second(original data\n\nsource: success (1))",
        "offline",
    )
    await close(w, store)


async def test_fanin_without_reuse_omits_original_input_and_model_call(tmp_path):
    w, store, _, ai, _ = service(tmp_path / "runs.sqlite3")
    result = await run(w, snapshot(
        channels=False, fan_in=FanInConfig(reuse_from=None, order=["second"]),
    ))
    assert result.status == "completed"
    assert result.outputs["final"] == "second(original data\n\nsource: success (1))"
    assert {call[0] for call in ai.calls} == {"first", "second"}
    await close(w, store)


@pytest.mark.parametrize(
    "policy,partial,status,sends",
    [
        ("continue", True, "partial", 2),
        ("continue", False, "failed", 0),
        ("stop", True, "failed", 0),
    ],
)
async def test_analysis_failure_policy(tmp_path, policy, partial, status, sends):
    w, store, _, _, n = service(tmp_path / "runs.sqlite3", ai=AI(fail={"second"}))
    result = await run(w, snapshot(analysis_failure=policy, send_partial=partial))
    assert result.status == status and len(n.calls) == sends
    await close(w, store)


async def test_aggregate_failure_does_not_fallback_to_branch_delivery(tmp_path):
    w, store, _, a, n = service(tmp_path / "runs.sqlite3", ai=AI(fail={"final"}))
    result = await run(w, snapshot(fan_in=FanInConfig(
        ai="ai", model="offline", reuse_from=None,
    )))
    assert result.status == "failed" and result.aggregate.status == "failed"
    assert not result.outputs and not n.calls
    await close(w, store)


def test_in_memory_database_is_rejected():
    with pytest.raises(LogAgentError):
        WorkflowService(Collector(), AI(), Channel(), database=":memory:")


async def test_coordinator_completion_cache_is_bounded():
    from logagent.workflow import RunCoordinator

    coordinator = RunCoordinator()

    async def value():
        return 1

    for i in range(coordinator.COMPLETED_LIMIT + 5):
        coordinator.submit(str(i), value)
        assert await coordinator.wait(str(i)) == 1
    assert len(coordinator._completed) <= coordinator.COMPLETED_LIMIT
    await coordinator.shutdown()


@pytest.mark.parametrize("failure", ["second", "final"])
async def test_failed_work_requires_explicit_stage_rerun(tmp_path, failure):
    w, store, c, _, n = service(tmp_path / "runs.sqlite3", ai=AI(fail={failure}))
    definition = snapshot(
        analysis_failure="stop", fan_in=FanInConfig(
            ai="ai", model="offline", reuse_from=None,
        ) if failure == "final" else None
    )
    first = await run(w, definition)
    assert first.status == "failed" and not n.calls
    w.ai_service = AI()
    await w.recover("run")
    result = await w.wait("run")
    assert result.status == "failed"
    assert not w.ai_service.calls
    await w.resume("run", stage="aggregate" if failure == "final" else "analyze")
    assert (await w.wait("run")).status == "completed"
    assert {row[0] for row in w.ai_service.calls} == ({"final"} if failure == "final" else {"first", "second"})
    assert c.calls == ["source"]
    await close(w, store)


@pytest.mark.parametrize("damage", ["missing", "corrupt", "expired"])
async def test_archive_damage_does_not_replace_checkpoint_execution_authority(tmp_path, damage):
    from datetime import timedelta

    from logagent.models import BackupPolicy

    path = tmp_path / "runs.sqlite3"
    w, store, c, a, n = service(path)
    await run(w, snapshot(backup=BackupPolicy(final_retention_days=1)))
    calls = (list(c.calls), list(a.calls), list(n.calls))
    if damage == "expired":
        assert await asyncio.to_thread(store.expire, datetime.now(UTC) + timedelta(days=2)) > 0
        assert (await w.get_session("run")).status == "completed"
    else:
        with store._transaction() as db:
            from logagent.workflow.session_models import ReportBody
            key = archived(store, "run", "output:first")["write_key"]
            entry = db.exec(select(SessionEntry).where(
                SessionEntry.session_id == "run", SessionEntry.write_key == key,
            )).one()
            body = db.get(ReportBody, (entry.session_id, entry.version))
            if damage == "missing":
                db.delete(body)
            else:
                body.content = '{"text":"private-content"}'
                db.add(body)
    assert (await w.recovery_availability("run")).available
    if damage == "expired":
        await w.recover("run")
        assert (await w.wait("run")).status == "completed"
    else:
        record = await w.get_session("run")
        with pytest.raises(LogAgentError) as error:
            await w.session_view.get_phase_content("run", "aggregate", version=record.version)
        assert error.value.code == "storage_corrupt"
        assert "private-content" not in str(error.value)
    assert calls == (c.calls, a.calls, n.calls)
    await close(w, store)


@pytest.mark.parametrize("on_failure", ["stop", "continue"])
async def test_body_backup_failure_preserves_checkpoint_for_later_reconciliation(tmp_path, on_failure):
    from logagent.models import BackupPolicy

    class BodyFailure(SessionStore):
        failing = True
        def write(self, sid, key, **kwargs):
            if self.failing and key.startswith("collect:item:source:epoch:") and kwargs.get("body") is not None:
                raise OperationalError(None, None, RuntimeError("body unavailable"))
            return super().write(sid, key, **kwargs)

    w, store, c, a, n = service(tmp_path / "runs.sqlite3", store_type=BodyFailure)
    definition = snapshot(backup=BackupPolicy(on_failure=on_failure))
    if on_failure == "stop":
        with pytest.raises(LogAgentError, match="备份策略"):
            await run(w, definition)
    else:
        result = await run(w, definition)
        assert result.status == "partial" and n.calls
    _, history = store.entries("run")
    errors = [entry for entry in history if entry["scope"] == "archive_error"]
    assert errors and errors[0]["summary"]["result_key"].startswith("collect:item:source:epoch:")
    assert archived(store, "run", "collect:item:source") is None
    assert c.calls == ["source"]
    store.failing = False
    await w.recover("run")
    assert (await w.wait("run")).status == "completed"
    assert c.calls == ["source"]
    _, history = store.entries("run")
    assert sum(entry["write_key"].startswith("collect:item:source:epoch:") for entry in history) == 1
    assert not store.archive_incomplete("run")
    await close(w, store)


async def test_reconcile_interrupted_preserves_events_without_running_business(tmp_path):
    from logagent.models import BackupPolicy

    w, store, c, a, n = service(tmp_path / "runs.sqlite3")
    store.create("orphan", "demo", BackupPolicy())
    await w.reconcile_interrupted()
    record = await w.get_session("orphan")
    assert record.status == "interrupted"
    await w.reconcile_interrupted()
    assert (await w.get_session("orphan")).version == record.version
    assert not c.calls and not a.calls and not n.calls
    await close(w, store)


async def test_notification_node_names_do_not_collide_for_underscored_ids(tmp_path):
    w, store, _, _, n = service(tmp_path / "runs.sqlite3")
    definition = snapshot(tasks=("a_b", "a"))
    definition.workflow.channels = ["c", "b_c"]
    definition.channels = {
        cid: ChannelConfig(id=cid, channel="mock") for cid in definition.workflow.channels
    }
    result = await run(w, definition)
    assert result.status == "completed"
    assert {(row[0], row[1]) for row in n.calls} == {("a_b", "c"), ("a_b", "b_c"), ("a", "c"), ("a", "b_c")}
    await close(w, store)


async def test_created_session_cannot_be_reused_after_snapshot_write_failure(tmp_path):
    class BrokenSnapshot(SessionStore):
        def write(self, sid, key, **kwargs):
            if key == "snapshot":
                raise RuntimeError("snapshot write interrupted")
            return super().write(sid, key, **kwargs)

    w, store, c, a, n = service(tmp_path / "runs.sqlite3", store_type=BrokenSnapshot)
    await w.trigger(snapshot(), session_id="run")
    with pytest.raises(LogAgentError):
        await w.wait("run")
    assert (await w.get_session("run")).status == "interrupted"
    with pytest.raises(LogAgentError) as error:
        await w.trigger(snapshot(), session_id="run")
    assert error.value.code == "session_exists"
    await close(w, store)


async def test_final_archive_replay_reconciles_interrupted_summary(tmp_path):
    class CrashAfterFinal(SessionStore):
        failed = False

        def write(self, sid, key, **kwargs):
            value = super().write(sid, key, **kwargs)
            if key.startswith("phase:finish:epoch:") and not self.failed:
                self.failed = True
                raise RuntimeError("after final business commit")
            return value

    w, store, c, a, n = service(tmp_path / "runs.sqlite3", store_type=CrashAfterFinal)
    with pytest.raises(LogAgentError):
        await run(w)
    assert (await w.get_session("run")).status == "interrupted"
    calls = (list(c.calls), list(a.calls), list(n.calls))
    await w.recover("run")
    assert (await w.wait("run")).status == "completed"
    assert (await w.get_session("run")).status == "completed"
    assert calls == (c.calls, a.calls, n.calls)
    await close(w, store)


async def test_unsaved_definition_is_not_silently_replaced_by_same_id(tmp_path):
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3")
    with pytest.raises(LogAgentError):
        await w.trigger(snapshot().workflow)
    await close(w, store)


async def test_collector_cannot_swallow_cancellation_and_start_analysis(tmp_path):
    entered = asyncio.Event()

    class SwallowingCollector:
        async def collect(self, config, context):
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                return CollectionResult(source_id=config.id, status="success", text="late", count=1)

    w, store, _, a, n = service(tmp_path / "runs.sqlite3")
    w.collector_manager = SwallowingCollector()
    await w.trigger(snapshot(), session_id="run")
    await entered.wait()
    await w.cancel("run")
    assert (await w.wait("run")).status == "cancelled"
    assert not a.calls and not n.calls
    await close(w, store)
