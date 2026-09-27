"""Workflow 原生 checkpoint 与业务存档恢复测试。

注入可控采集/AI/通知替身，使用真实 SQLite 和 WorkflowService，验证阶段
顺序、fan-in、失败策略、取消、容量、关闭和旧快照恢复；在写入与回执边界
注入故障，断言成功步骤不重复，材料缺失或损坏明确拒绝，投递不确定不重发。
"""

import asyncio
from copy import deepcopy
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
from tests.workflow.helpers import AI, Channel, Collector, snapshot


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
    assert [row[:2] for row in n.calls] == [
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
    assert "" in namespaces and any(ns.startswith("collect:") for ns in namespaces)
    assert any(ns.startswith("analyze:") for ns in namespaces)
    assert any(ns.startswith("notify:") for ns in namespaces)
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
    assert (await asyncio.to_thread(store.entry, "run", "analyze:item:first"))["body"][
        "status"
    ] == "success"
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


async def test_recovery_reads_legacy_prompt_snapshot_without_rewriting_archive(tmp_path):
    class LegacySnapshotStore(SessionStore):
        def write(self, sid, key, **kwargs):
            if key == "snapshot":
                body = deepcopy(kwargs["body"])
                workflow = body["snapshot"]["workflow"]
                del workflow["system_prompt"], workflow["input_prompt"]
                task = workflow["analyses"][0]
                task["prompt"] = "legacy task"
                del task["system_prompt"], task["input_prompt"], task["user_prompt"]
                kwargs["body"] = body
            return super().write(sid, key, **kwargs)

    path = tmp_path / "runs.sqlite3"
    blocked = AI(block="first")
    original, store, _, _, _ = service(path, ai=blocked, store_type=LegacySnapshotStore)
    snap = snapshot(channels=False, tasks=("first",), system_prompt="legacy system")
    snap.workflow.analyses[0].input_prompt = "legacy task\n\n{input}"
    snap.ai["ai"].system_prompt = "legacy system"
    await original.trigger(snap, session_id="run")
    await asyncio.wait_for(blocked.started.wait(), 5)
    assert await original.cancel("run")
    assert (await original.wait("run")).status == "cancelled"
    await close(original, store)

    recovered, archive, _, ai, _ = service(path)
    assert (await asyncio.to_thread(archive.entry, "run", "snapshot"))["body"][
        "snapshot"
    ]["workflow"]["analyses"][0]["prompt"] == "legacy task"
    await recovered.recover("run")
    assert (await recovered.wait("run")).status == "completed"
    assert ai.requests == [
        ("first", "ai", "legacy task\n\n{input}", "legacy system", "")
    ]
    assert (await asyncio.to_thread(archive.entry, "run", "snapshot"))["body"][
        "snapshot"
    ]["workflow"]["analyses"][0]["prompt"] == "legacy task"
    await close(recovered, archive)


async def test_business_commit_before_checkpoint_replays_without_external_call(tmp_path):
    class FailAfterArchive(SessionStore):
        def write(self, sid, key, **kwargs):
            entry = super().write(sid, key, **kwargs)
            if key == "collect:item:source":
                raise RuntimeError("process interruption after archive commit")
            return entry

    path = tmp_path / "runs.sqlite3"
    w, store, c, a, n = service(path, store_type=FailAfterArchive)
    with pytest.raises(LogAgentError):
        await run(w)
    assert c.calls == ["source"] and not a.calls and not n.calls
    await close(w, store)
    new, reopened, c, _, _ = service(path)
    await new.recover("run")
    assert (await new.wait("run")).status == "completed"
    assert not c.calls
    await close(new, reopened)


async def test_send_receipt_failure_preserves_uncertainty_and_next_target(tmp_path):
    class FailReceipt(SessionStore):
        def write(self, sid, key, **kwargs):
            if key == "delivery:first:one":
                raise RuntimeError("receipt disk failure")
            return super().write(sid, key, **kwargs)

    path = tmp_path / "runs.sqlite3"
    w, store, _, _, n = service(path, store_type=FailReceipt)
    with pytest.raises(LogAgentError):
        await run(w, snapshot(tasks=("first",)))
    assert [row[:2] for row in n.calls] == [("first", "one")]
    await close(w, store)
    new, reopened, c, a, n = service(path)
    await new.recover("run")
    result = await new.wait("run")
    assert result.status == "partial" and not c.calls and not a.calls
    assert [row[:2] for row in n.calls] == [("first", "two")]
    assert result.deliveries[0].error.code == "delivery_uncertain"
    assert result.deliveries[1].status == "success"
    await close(new, reopened)


async def test_intent_storage_failure_prevents_send_and_retains_unwaited_error(tmp_path):
    class FailIntent(SessionStore):
        def write(self, sid, key, **kwargs):
            if key.startswith("intent:"):
                raise RuntimeError("private disk path")
            return super().write(sid, key, **kwargs)

    w, store, _, _, channel = service(tmp_path / "runs.sqlite3", store_type=FailIntent)
    await w.trigger(snapshot(), session_id="run")
    for _ in range(1000):
        if not w.coordinator.active:
            break
        await asyncio.sleep(0.001)
    with pytest.raises(LogAgentError) as caught:
        await w.wait("run")
    assert "private" not in str(caught.value) and not channel.calls
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
async def test_disabled_required_body_refuses_recovery_and_checkpoint_has_no_body(
    tmp_path, category
):
    from logagent.models import BackupPolicy

    policy = BackupPolicy(**{category: False})
    # Block before outputs freeze to make collection/analysis necessary.
    ai = AI(block="second") if category in {"collection", "analysis"} else AI()
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3", ai=ai)
    await w.trigger(snapshot(backup=policy, analysis_concurrency=1), session_id="run")
    if ai.block:
        await asyncio.wait_for(ai.started.wait(), 5)
        await w.cancel("run")
    await w.wait("run")
    with pytest.raises(LogAgentError) as caught:
        await w.recover("run")
    assert caught.value.code == "recovery_unavailable"
    async for checkpoint in w._checkpointer.alist(None):
        # All categories, even when enabled, remain out of checkpoint channels.
        encoded = repr(checkpoint.checkpoint) + repr(checkpoint.pending_writes)
        assert "original data" not in encoded
        assert "offline" not in encoded
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
async def test_failed_work_recovery_reuses_successful_branches(tmp_path, failure):
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
    assert result.status == "completed"
    assert [row[0] for row in w.ai_service.calls] == [failure]
    assert c.calls == ["source"]
    await close(w, store)


@pytest.mark.parametrize("damage", ["missing", "corrupt", "expired"])
async def test_recovery_refuses_missing_corrupt_or_expired_archives(tmp_path, damage):
    from datetime import timedelta

    from logagent.models import BackupPolicy

    path = tmp_path / "runs.sqlite3"
    w, store, c, a, n = service(path)
    await run(w, snapshot(backup=BackupPolicy(retention_days=1)))
    calls = (list(c.calls), list(a.calls), list(n.calls))
    if damage == "expired":
        assert await asyncio.to_thread(store.expire, datetime.now(UTC) + timedelta(days=2)) > 0
        assert (await w.get_session("run")).status == "completed"
    else:
        with store._transaction() as db:
            key = "analyze:item:first" if damage == "missing" else "phase:aggregate"
            entry = db.exec(select(SessionEntry).where(
                SessionEntry.session_id == "run", SessionEntry.write_key == key,
            )).one()
            if damage == "missing":
                db.delete(entry)
            else:
                entry.body = '{"text":"private-content"}'
                db.add(entry)
    with pytest.raises(LogAgentError) as error:
        await w.recover("run")
    assert error.value.code in {"recovery_unavailable", "storage_corrupt"}
    assert "private-content" not in str(error.value)
    assert calls == (c.calls, a.calls, n.calls)
    await close(w, store)


@pytest.mark.parametrize("on_failure", ["stop", "continue"])
async def test_body_backup_failure_is_recorded_and_stop_cannot_replay_past_it(tmp_path, on_failure):
    from logagent.models import BackupPolicy

    class BodyFailure(SessionStore):
        def write(self, sid, key, **kwargs):
            if key == "collect:item:source" and kwargs.get("body") is not None:
                raise OperationalError(None, None, RuntimeError("body unavailable"))
            return super().write(sid, key, **kwargs)

    w, store, _, a, n = service(tmp_path / "runs.sqlite3", store_type=BodyFailure)
    definition = snapshot(backup=BackupPolicy(on_failure=on_failure))
    if on_failure == "stop":
        with pytest.raises(LogAgentError, match="备份策略"):
            await run(w, definition)
        with pytest.raises(LogAgentError):
            await w.recover("run")
        assert not a.calls and not n.calls
    else:
        result = await run(w, definition)
        assert result.status == "partial" and n.calls
    entry = await asyncio.to_thread(store.entry, "run", "collect:item:source")
    assert entry["availability"] == "write_failed" and entry["body"] is None
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
    assert [row[:2] for row in n.calls] == [("a_b", "c"), ("a_b", "b_c"), ("a", "c"), ("a", "b_c")]
    await close(w, store)


async def test_created_session_cannot_be_reused_after_snapshot_write_failure(tmp_path):
    class BrokenSnapshot(SessionStore):
        def write(self, sid, key, **kwargs):
            if key == "snapshot":
                raise RuntimeError("snapshot write interrupted")
            return super().write(sid, key, **kwargs)

    w, store, c, a, n = service(tmp_path / "runs.sqlite3", store_type=BrokenSnapshot)
    with pytest.raises(RuntimeError):
        await w.trigger(snapshot(), session_id="run")
    assert (await w.get_session("run")).status == "created"
    with pytest.raises(LogAgentError) as error:
        await w.trigger(snapshot(), session_id="run")
    assert error.value.code == "session_exists" and not c.calls and not a.calls and not n.calls
    await close(w, store)


async def test_final_archive_replay_reconciles_interrupted_summary(tmp_path):
    class CrashAfterFinal(SessionStore):
        failed = False

        def write(self, sid, key, **kwargs):
            value = super().write(sid, key, **kwargs)
            if key == "phase:finish" and not self.failed:
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


async def test_recovery_reads_legacy_schedule_in_persisted_snapshot(tmp_path):
    class LegacySnapshots(SessionStore):
        def write(self, sid, key, **kwargs):
            if key == "snapshot":
                saved = kwargs["body"]["snapshot"]["workflow"]
                saved.pop("schedule")
                saved.update(interval_seconds=None, cron="0 9 * * 1", cron_timezone="UTC")
            return super().write(sid, key, **kwargs)

    path = tmp_path / "legacy.sqlite3"
    workflow, store, _, _, _ = service(path, store_type=LegacySnapshots)
    result = await run(workflow)
    await close(workflow, store)
    restored, reopened, collector, ai, channel = service(path)
    try:
        assert (await restored.recovery_availability("run")).available
        await restored.recover("run")
        assert await restored.wait("run") == result
        assert not collector.calls and not ai.calls and not channel.calls
    finally:
        await close(restored, reopened)
