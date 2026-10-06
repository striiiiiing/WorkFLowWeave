"""Workflow 原生 checkpoint 与业务存档恢复测试。

注入可控采集/AI/通知替身，使用真实 SQLite 和 WorkflowRunner，验证阶段
顺序、fan-in、失败策略、取消、容量、关闭和旧快照恢复；在写入与回执边界
注入故障，断言成功步骤不重复，材料缺失或损坏明确拒绝，投递不确定不重发。
"""

import asyncio
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import select

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import (
    AIConfig,
    AnalysisResult,
    ChannelConfig,
    CollectionResult,
    ErrorInfo,
    FanInConfig,
    SourceConfig,
)
from workflowweave.workflow.execution.runner import WorkflowRunner
from workflowweave.workflow.execution.tasks import RunCoordinator
from workflowweave.workflow.storage.facts import SessionStore
from workflowweave.workflow.storage.models import ReportBody, SessionEntry
from tests.workflow.helpers import AI, Channel, Collector, archived, snapshot


def service(path, *, ai=None, store_type=SessionStore):
    c, a, n = Collector(), ai or AI(), Channel()
    store = store_type(path)
    return WorkflowRunner(c, a, n, session_store=store), store, c, a, n


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
    assert result.status == "completed" and result.shared_input == "[source=source; format=none]\noriginal data"
    assert sorted(row[:2] for row in n.calls) == [
        ("first", "one"),
        ("first", "two"),
        ("second", "one"),
        ("second", "two"),
    ]
    assert [
        e["stage"]
        for e in await w.history("run")
        if e["scope"] == "phase" and e["summary"].get("progress_status") != "running"
    ] == [
        "collect",
        "analyze",
        "aggregate",
        "notify",
        "finish",
    ]
    record = await w.get_session("run")
    assert record.status == "completed"
    content = await w.session_view.get_phase_content("run", "collect", version=record.version)
    assert content.content["shared_input"] == "[source=source; format=none]\noriginal data"
    namespaces = {
        checkpoint.config["configurable"]["checkpoint_ns"]
        async for checkpoint in w._checkpointer.alist(None)
    }
    assert namespaces == {""}
    await close(w, store)
    new, reopened, c2, a2, n2 = service(path)
    await new.resume("run")
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
    namespaces = {
        checkpoint.config["configurable"]["checkpoint_ns"]
        async for checkpoint in w._checkpointer.alist(None)
    }
    assert any(namespace.startswith(("collect:", "analyze:")) for namespace in namespaces)
    _, _, graph, _ = await w._recovery_material("run")
    subgraphs = dict(graph.get_subgraphs())
    assert {"collect", "analyze", "aggregate", "notify"} <= subgraphs.keys()
    parent_state = await graph.aget_state({"configurable": {"thread_id": "run"}})
    assert parent_state.next and parent_state.values["status"] == "running"
    snap.ai["ai"].models = {"changed": {}}
    await close(w, store)
    new, reopened, c, a, n = service(path)
    await new.resume("run")
    result = await new.wait("run")
    assert result.status == "completed"
    assert not c.calls and a.calls == [("second", "[source=source; format=none]\noriginal data", "offline")]
    assert len(n.calls) == 4
    namespaces = {
        checkpoint.config["configurable"]["checkpoint_ns"]
        async for checkpoint in new._checkpointer.alist(None)
    }
    assert namespaces == {""}
    await close(new, reopened)


async def test_runtime_context_isolated_for_concurrent_snapshots(tmp_path):
    class ContextCollector:
        def __init__(self):
            self.sessions = set()
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = []

        async def collect(self, config, context):
            self.calls.append((context.session_id, context.workflow_id, config.id))
            self.sessions.add(context.session_id)
            if len(self.sessions) == 2:
                self.started.set()
            await self.release.wait()
            return CollectionResult(
                source_id=config.id,
                status="success",
                text=f"{context.session_id}:{context.workflow_id}",
                count=1,
            )

    class ContextAI:
        def __init__(self):
            self.calls = []

        async def execute(self, config, prompt, text, *, model, task_id, context,
                          system_prompt=None, user_prompt=""):
            self.calls.append((
                context.session_id, context.workflow_id, config.id, model, text,
            ))
            return AnalysisResult(
                task_id=task_id, status="success", text=f"{config.id}:{text}"
            )

    collector, ai = ContextCollector(), ContextAI()
    store = SessionStore(tmp_path / "runs.sqlite3")
    w = WorkflowRunner(collector, ai, Channel(), session_store=store)

    def isolated_snapshot(workflow_id, source_id, ai_id, model):
        definition = snapshot(tasks=("analysis",), channels=False)
        definition.workflow.id = workflow_id
        definition.workflow.sources = [source_id]
        definition.workflow.analyses[0].ai = ai_id
        definition.workflow.analyses[0].model = model
        definition.sources = {
            source_id: SourceConfig(id=source_id, collector="mock"),
        }
        definition.ai = {
            ai_id: AIConfig(id=ai_id, provider="mock", models={model: {}}),
        }
        return definition

    first = isolated_snapshot("workflow-one", "source-one", "ai-one", "model-one")
    second = isolated_snapshot("workflow-two", "source-two", "ai-two", "model-two")
    await w.trigger(first, session_id="session-one")
    await w.trigger(second, session_id="session-two")
    try:
        async with asyncio.timeout(5):
            await collector.started.wait()
        collector.release.set()
        first_result, second_result = await asyncio.gather(
            w.wait("session-one"), w.wait("session-two"),
        )
        assert first_result.status == second_result.status == "completed"
        assert sorted(collector.calls) == [
            ("session-one", "workflow-one", "source-one"),
            ("session-two", "workflow-two", "source-two"),
        ]
        assert sorted((sid, workflow_id, ai_id, model) for sid, workflow_id, ai_id, model, _ in ai.calls) == [
            ("session-one", "workflow-one", "ai-one", "model-one"),
            ("session-two", "workflow-two", "ai-two", "model-two"),
        ]
        assert all(f"{sid}:{workflow_id}" in text for sid, workflow_id, _, _, text in ai.calls)
    finally:
        collector.release.set()
        await close(w, store)


async def test_deferred_cleanup_failure_keeps_checkpoint_for_recovery(tmp_path):
    path = tmp_path / "runs.sqlite3"
    w, store, _, _, _ = service(path)
    await w.start()
    finalize = w._cleanup.finalize
    attempts = 0

    async def fail_once(session_id):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("injected deferred cleanup failure")
        await finalize(session_id)

    w._cleanup.finalize = fail_once
    try:
        await w.trigger(snapshot(tasks=("first",), channels=False), session_id="run")
        with pytest.raises(OSError, match="injected deferred cleanup failure"):
            await w.wait("run")
        namespaces = {
            checkpoint.config["configurable"]["checkpoint_ns"]
            async for checkpoint in w._checkpointer.alist(None)
        }
        assert any(namespace.startswith("collect:") for namespace in namespaces)

        await w.resume("run")
        assert (await w.wait("run")).status == "completed"
        namespaces = {
            checkpoint.config["configurable"]["checkpoint_ns"]
            async for checkpoint in w._checkpointer.alist(None)
        }
        assert namespaces == {""}
        assert attempts == 2
    finally:
        await close(w, store)


@pytest.mark.parametrize(
    ("timeout_stage", "policy", "expected_status", "expected_analysis_calls"),
    [
        ("collect", "skip", "partial", ["first"]),
        ("collect", "stop", "failed", []),
        ("analyze", "continue", "partial", ["first", "second"]),
        ("analyze", "stop", "failed", ["first", "second"]),
    ],
)
async def test_business_timeouts_follow_workflow_stage_policy(
    tmp_path, timeout_stage, policy, expected_status, expected_analysis_calls
):
    class ResultCollector:
        async def collect(self, source, context):
            if timeout_stage == "collect" and source.id == "slow":
                return CollectionResult(
                    source_id=source.id,
                    status="timeout",
                    error=ErrorInfo(code="collection_timeout", message="timed out"),
                )
            return CollectionResult(
                source_id=source.id, status="success", text="available input", count=1
            )

    class ResultAI:
        def __init__(self):
            self.calls = []

        async def execute(self, config, prompt, text, *, model, task_id, context,
                          system_prompt=None, user_prompt=""):
            self.calls.append(task_id)
            if timeout_stage == "analyze" and task_id == "second":
                return AnalysisResult(
                    task_id=task_id,
                    status="timeout",
                    error=ErrorInfo(code="ai_timeout", message="timed out"),
                )
            return AnalysisResult(task_id=task_id, status="success", text=f"{task_id}({text})")

    analysis_tasks = ("first", "second") if timeout_stage == "analyze" else ("first",)
    definition = snapshot(
        tasks=analysis_tasks,
        channels=False,
        analysis_failure=policy if timeout_stage == "analyze" else "continue",
    )
    definition.workflow.sources = ["slow", "source"]
    definition.sources = {
        "slow": SourceConfig(
            id="slow", collector="mock", on_error=policy if timeout_stage == "collect" else "skip"
        ),
        "source": SourceConfig(id="source", collector="mock"),
    }
    collector, ai = ResultCollector(), ResultAI()
    store = SessionStore(tmp_path / "runs.sqlite3")
    w = WorkflowRunner(collector, ai, Channel(), session_store=store)
    try:
        result = await run(w, definition)
        assert result.status == expected_status
        assert ai.calls == expected_analysis_calls
        if timeout_stage == "collect":
            timeout_result = archived(store, "run", "collect:item:slow")
            assert timeout_result["body"]["status"] == "timeout"
        else:
            timeout_result = archived(store, "run", "analyze:item:second")
            assert timeout_result["body"]["status"] == "timeout"
        if expected_status == "partial" and timeout_stage == "analyze":
                assert result.outputs == {
                    "first": "first([source=slow; format=none]\navailable input\n\n[source=source; format=none]\navailable input)"
                }
    finally:
        await close(w, store)


async def test_cancelled_ai_result_without_task_cancellation_is_a_business_failure(tmp_path):
    class CancelledAI:
        async def execute(self, config, prompt, text, *, model, task_id, context,
                          system_prompt=None, user_prompt=""):
            if task_id == "second":
                return AnalysisResult(
                    task_id=task_id,
                    status="cancelled",
                    error=ErrorInfo(code="ai_cancelled", message="request cancelled"),
                )
            return AnalysisResult(task_id=task_id, status="success", text=f"{task_id}({text})")

    w, store, _, _, _ = service(tmp_path / "runs.sqlite3", ai=CancelledAI())
    result = await run(w, snapshot(channels=False))
    assert result.status == "partial" and not result.cancelled
    assert set(result.outputs) == {"first"}
    cancelled = archived(store, "run", "analyze:item:second")
    assert cancelled["body"]["status"] == "cancelled"
    await close(w, store)


async def test_checkpoint_fact_survives_archive_interruption_and_recovery(tmp_path):
    class FailAfterArchive(SessionStore):
        def write(self, sid, key, **kwargs):
            entry = super().write(sid, key, **kwargs)
            if key.startswith("collect:item:source:epoch:"):
                raise RuntimeError("process interruption after archive commit")
            return entry

    path = tmp_path / "runs.sqlite3"
    w, store, c, a, n = service(path, store_type=FailAfterArchive)
    with pytest.raises(RuntimeError, match="process interruption after archive commit"):
        await run(w)
    assert c.calls == ["source"]
    await close(w, store)
    new, reopened, c, _, _ = service(path)
    await new.resume("run")
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
    with pytest.raises(OperationalError, match="receipt disk failure"):
        await run(w, snapshot(tasks=("first",)))
    original_deliveries = [row[:2] for row in n.calls]
    assert original_deliveries.count(("first", "one")) == 1
    await close(w, store)
    new, reopened, c, a, n = service(path)
    await new.resume("run")
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
    with pytest.raises(RuntimeError, match="intent checkpoint failure"):
        await w.wait("run")
    assert not channel.calls
    assert (await w.get_session("run")).status == "interrupted"
    await close(w, store)


async def test_missing_checkpoint_is_not_reconstructed_from_business_history(tmp_path):
    path = tmp_path / "runs.sqlite3"
    w, store, _, _, _ = service(path)
    await run(w)
    await w._checkpointer.adelete_thread("run")
    with pytest.raises(WorkFLowWeaveError) as caught:
        await w.resume("run")
    assert caught.value.code == "checkpoint_missing"
    assert (await w.get_session("run")).status == "completed"
    await close(w, store)


@pytest.mark.parametrize("category", ["snapshot", "collection", "analysis", "final"])
async def test_disabled_archive_does_not_disable_checkpoint_recovery(
    tmp_path, category
):
    from workflowweave.models import BackupPolicy

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
    await w.resume("run")
    assert (await w.wait("run")).status == "completed"
    await close(w, store)


async def test_duplicate_capacity_and_shutdown(tmp_path):
    ai = AI(block="first")
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3", ai=ai)
    w.coordinator._max = 1
    await w.trigger(snapshot(), session_id="run")
    await asyncio.wait_for(ai.started.wait(), 5)
    with pytest.raises(WorkFLowWeaveError, match="同一 session"):
        await w.resume("run")
    with pytest.raises(WorkFLowWeaveError, match="容量"):
        await w.trigger(snapshot(), session_id="other")
    await w.shutdown()
    assert (await w.wait("run")).status == "cancelled"
    with pytest.raises(WorkFLowWeaveError, match="关闭"):
        await w.resume("run")
    store.close()


@pytest.mark.parametrize(
    "fan_in", [None, FanInConfig(user_prompt="summarize results"), FanInConfig(user_prompt="summarize results",
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
    snap.workflow.analyses[1].input_prompt = "{input}"
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
    assert by_id["second"] == ("second", "other", "{input}", "shared {input}", "analyze input")
    assert by_id["final"] == ("final", "other", "body: {input}", "", "summary {input}")
    assert ai.calls[-1] == (
        "final",
        "second([source=source; format=none]\noriginal data)\n\n"
        "[source=source; format=none]\noriginal data\n\n"
        "first([source=source; format=none]\noriginal data)",
        "other-model",
    )
    await close(w, store)


async def test_default_fanin_reuses_first_model_and_declared_order(tmp_path):
    w, store, _, ai, _ = service(tmp_path / "runs.sqlite3")
    snap = snapshot(channels=False, fan_in=FanInConfig(user_prompt="summarize results"), system_prompt="shared system")
    snap.ai["ai"].system_prompt = "ignored AI system"
    result = await run(w, snap)
    assert result.status == "completed"
    assert ai.requests[-1][3] == "shared system"
    assert ai.calls[-1] == (
        "final",
        "[source=source; format=none]\noriginal data\n\n"
        "first([source=source; format=none]\noriginal data)\n\n"
        "second([source=source; format=none]\noriginal data)",
        "offline",
    )
    await close(w, store)


async def test_fanin_without_reuse_omits_original_input_and_model_call(tmp_path):
    w, store, _, ai, _ = service(tmp_path / "runs.sqlite3")
    result = await run(w, snapshot(
        channels=False, fan_in=FanInConfig(user_prompt="summarize results", reuse_from=None, order=["second"]),
    ))
    assert result.status == "completed"
    assert result.outputs["final"] == "second([source=source; format=none]\noriginal data)"
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
    result = await run(w, snapshot(fan_in=FanInConfig(user_prompt="summarize results",
        ai="ai", model="offline", reuse_from=None,
    )))
    assert result.status == "failed" and result.aggregate.status == "failed"
    assert not result.outputs and not n.calls
    await close(w, store)


def test_in_memory_database_is_rejected():
    with pytest.raises(WorkFLowWeaveError):
        WorkflowRunner(Collector(), AI(), Channel(), database=":memory:")


async def test_coordinator_completion_cache_is_bounded():
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
        analysis_failure="stop", fan_in=FanInConfig(user_prompt="summarize results",
            ai="ai", model="offline", reuse_from=None,
        ) if failure == "final" else None
    )
    first = await run(w, definition)
    assert first.status == "failed" and not n.calls
    w.ai_service = AI()
    await w.resume("run")
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

    from workflowweave.models import BackupPolicy

    path = tmp_path / "runs.sqlite3"
    w, store, c, a, n = service(path)
    await run(w, snapshot(backup=BackupPolicy(final_retention_days=1)))
    calls = (list(c.calls), list(a.calls), list(n.calls))
    if damage == "expired":
        assert await asyncio.to_thread(store.expire, datetime.now(UTC) + timedelta(days=2)) > 0
        assert (await w.get_session("run")).status == "completed"
    else:
        with store._transaction() as db:
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
        await w.resume("run")
        assert (await w.wait("run")).status == "completed"
    else:
        record = await w.get_session("run")
        with pytest.raises(WorkFLowWeaveError) as error:
            await w.session_view.get_phase_content("run", "aggregate", version=record.version)
        assert error.value.code == "storage_corrupt"
        assert "private-content" not in str(error.value)
    assert calls == (c.calls, a.calls, n.calls)
    await close(w, store)


@pytest.mark.parametrize("on_failure", ["stop", "continue"])
async def test_body_backup_failure_preserves_checkpoint_for_later_reconciliation(tmp_path, on_failure):
    from workflowweave.models import BackupPolicy

    class BodyFailure(SessionStore):
        failing = True
        def write(self, sid, key, **kwargs):
            if self.failing and key.startswith("collect:item:source:epoch:") and kwargs.get("body") is not None:
                raise OperationalError(None, None, RuntimeError("body unavailable"))
            return super().write(sid, key, **kwargs)

    w, store, c, a, n = service(tmp_path / "runs.sqlite3", store_type=BodyFailure)
    definition = snapshot(backup=BackupPolicy(on_failure=on_failure))
    if on_failure == "stop":
        with pytest.raises(WorkFLowWeaveError, match="备份策略"):
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
    await w.resume("run")
    assert (await w.wait("run")).status == "completed"
    assert c.calls == ["source"]
    _, history = store.entries("run")
    assert sum(entry["write_key"].startswith("collect:item:source:epoch:") for entry in history) == 1
    assert not store.archive_incomplete("run")
    await close(w, store)


async def test_reconcile_interrupted_preserves_events_without_running_business(tmp_path):
    from workflowweave.models import BackupPolicy

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
    with pytest.raises(RuntimeError, match="snapshot write interrupted"):
        await w.wait("run")
    assert (await w.get_session("run")).status == "interrupted"
    with pytest.raises(WorkFLowWeaveError) as error:
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
    with pytest.raises(RuntimeError, match="after final business commit"):
        await run(w)
    assert (await w.get_session("run")).status == "interrupted"
    calls = (list(c.calls), list(a.calls), list(n.calls))
    await w.resume("run")
    assert (await w.wait("run")).status == "completed"
    assert (await w.get_session("run")).status == "completed"
    assert calls == (c.calls, a.calls, n.calls)
    await close(w, store)


async def test_unsaved_definition_is_not_silently_replaced_by_same_id(tmp_path):
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3")
    with pytest.raises(WorkFLowWeaveError):
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
