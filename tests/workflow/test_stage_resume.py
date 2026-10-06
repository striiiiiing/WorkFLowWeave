"""阶段重跑始终经由真实父图入口，轮次与外部副作用彼此隔离。"""

import asyncio

import pytest
from sqlmodel import select

from logagent.errors import LogAgentError
from logagent.models import FanInConfig
from logagent.workflow.storage.models import SessionEntry
from tests.workflow.helpers import AI, archived, snapshot
from tests.workflow.test_workflow_recovery import close, run, service


async def test_analyze_and_notify_rerun_to_finish_without_recollecting(tmp_path):
    w, store, collector, ai, channel = service(tmp_path / "runs.sqlite3")
    try:
        first = await run(w, snapshot(fan_in=FanInConfig(user_prompt="summarize results", )))
        original = await w.get_session("run")
        cp = await w._checkpointer.aget_tuple({"configurable": {"thread_id": "run"}})
        epoch = cp.checkpoint["channel_values"]["execution_epoch"]
        await w.resume("run", stage="analyze", request_id="redo-analysis")
        second = await w.wait("run")
        assert second == first
        assert len(collector.calls) == 1
        assert [call[0] for call in ai.calls].count("first") == 2
        assert [call[0] for call in ai.calls].count("second") == 2
        assert [call[0] for call in ai.calls].count("final") == 2
        assert len(channel.calls) == 4
        cp = await w._checkpointer.aget_tuple({"configurable": {"thread_id": "run"}})
        assert cp.checkpoint["channel_values"]["execution_epoch"] != epoch
        await w.resume("run", stage="analyze", request_id="redo-analysis")
        assert len(ai.calls) == 6 and len(channel.calls) == 4
        await w.resume("run", stage="notify", request_id="redo-notify")
        assert (await w.wait("run")).status == "completed"
        assert len(ai.calls) == 6 and len(channel.calls) == 6
        old = await w.get_session("run", version=original.version)
        assert old == original
    finally:
        await close(w, store)


async def test_finished_business_failure_is_not_implicitly_retried(tmp_path):
    w, store, collector, _, channel = service(tmp_path / "runs.sqlite3", ai=AI(fail={"second"}))
    try:
        first = await run(w, snapshot(analysis_failure="stop"))
        assert first.status == "failed"
        w.ai_service = AI()
        await w.resume("run")
        assert (await w.wait("run")).status == "failed"
        assert not w.ai_service.calls and not channel.calls
        await w.resume("run", stage="analyze")
        assert (await w.wait("run")).status == "completed"
        assert {call[0] for call in w.ai_service.calls} == {"first", "second"}
        assert len(collector.calls) == 1
    finally:
        await close(w, store)


async def test_collect_rerun_clears_results_and_uses_new_invocation(tmp_path):
    w, store, collector, ai, channel = service(tmp_path / "runs.sqlite3")
    try:
        await run(w)
        await w.resume("run", stage="collect")
        assert (await w.wait("run")).status == "completed"
        assert len(collector.calls) == 2 and len(ai.calls) == 4 and len(channel.calls) == 8
    finally:
        await close(w, store)


async def test_stage_entry_and_request_validation(tmp_path):
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3")
    try:
        await run(w, snapshot(channels=False))
        with pytest.raises(LogAgentError, match="中断续跑"):
            await w.resume("run", checkpoint_id="unknown")
        with pytest.raises(LogAgentError) as invalid:
            await w.resume("run", stage="analyze", checkpoint_id="unknown")
        assert invalid.value.code == "stage_unavailable"
        await w.resume("run", stage="analyze", request_id="accepted")
        await w.wait("run")
        with pytest.raises(LogAgentError) as conflict:
            await w.resume("run", stage="notify", request_id="accepted")
        assert conflict.value.code == "request_conflict"
        # This new round starts at analyze; it must not silently select an old collect entry.
        assert not (await w.recovery_availability("run", stage="collect")).available
    finally:
        await close(w, store)


async def test_only_one_concurrent_resume_can_advance_thread(tmp_path):
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3")
    try:
        await run(w, snapshot(channels=False))
        blocker = AI(block="first")
        w.ai_service = blocker
        results = await asyncio.gather(
            w.resume("run", stage="analyze"), w.resume("run", stage="analyze"),
            return_exceptions=True,
        )
        assert results.count("run") == 1
        assert any(isinstance(value, LogAgentError) and value.code == "session_active" for value in results)
        await blocker.started.wait()
        await w.cancel("run")
        await w.wait("run")
    finally:
        await close(w, store)


async def test_request_replay_continues_epoch_committed_before_task_submission(tmp_path, monkeypatch):
    w, store, collector, ai, _ = service(tmp_path / "runs.sqlite3")
    try:
        await run(w, snapshot(channels=False))
        original = await w.get_session("run")
        event = w.archive.reconcile

        async def fail_epoch(*args, **kwargs):
            raise OSError("lost response before task submission")

        monkeypatch.setattr(w.archive, "reconcile", fail_epoch)
        with pytest.raises(OSError, match="lost response"):
            await w.resume("run", stage="analyze", request_id="accepted")
        saved = await w._checkpointer.aget_tuple({"configurable": {"thread_id": "run"}})
        accepted_epoch = saved.checkpoint["channel_values"]["execution_epoch"]
        assert accepted_epoch != original.execution_epoch
        assert not w.coordinator.contains("run")
        monkeypatch.setattr(w.archive, "reconcile", event)
        await w.resume("run", stage="analyze", request_id="accepted")
        assert (await w.wait("run")).status == "completed"
        assert (await w.get_session("run")).execution_epoch == accepted_epoch
        assert len(collector.calls) == 1 and len(ai.calls) == 4
        await w.resume("run", stage="analyze", request_id="accepted")
        assert len(ai.calls) == 4
        epochs = [e for e in await w.history("run") if e["write_key"] == f"epoch:{accepted_epoch}"]
        assert len(epochs) == 1
    finally:
        await close(w, store)


async def test_explicit_historical_parent_entry_and_foreign_checkpoint_rejection(tmp_path):
    w, store, collector, _, _ = service(tmp_path / "runs.sqlite3")
    try:
        await run(w, snapshot(channels=False))
        _, _, graph, entry = await w._recovery_material("run", stage="collect")
        original_id = entry.config["configurable"]["checkpoint_id"]
        await w.resume("run", stage="analyze")
        await w.wait("run")
        assert not (await w.recovery_availability("run", stage="collect")).available
        await w.resume("run", stage="collect", checkpoint_id=original_id)
        assert (await w.wait("run")).status == "completed"
        assert len(collector.calls) == 2
        await w.trigger(snapshot(channels=False), session_id="other")
        await w.wait("other")
        foreign = await graph.aget_state({"configurable": {"thread_id": "other"}})
        with pytest.raises(LogAgentError) as error:
            await w.resume("run", stage="collect",
                           checkpoint_id=foreign.config["configurable"]["checkpoint_id"])
        assert error.value.code == "stage_unavailable"
    finally:
        await close(w, store)


@pytest.mark.parametrize("missing_stage, available", [("aggregate", True), ("collect", True)])
async def test_stage_resume_requires_only_retained_upstream_material(tmp_path, missing_stage, available):
    w, store, collector, _, _ = service(tmp_path / "runs.sqlite3")
    try:
        await run(w, snapshot(channels=False))
        key = archived(store, "run", f"phase:{missing_stage}")["write_key"]
        with store._transaction() as db:
            row = db.exec(select(SessionEntry).where(
                SessionEntry.session_id == "run", SessionEntry.write_key == key,
            )).one()
            row.body, row.availability = None, "expired"
            db.add(row)
        eligibility = await w.recovery_availability("run", stage="analyze")
        assert eligibility.available is available
        if available:
            await w.resume("run", stage="analyze")
            assert (await w.wait("run")).status == "completed"
            assert len(collector.calls) == 1
        else:
            assert eligibility.reason.code == "recovery_unavailable"
    finally:
        await close(w, store)


async def test_historical_entry_queries_show_its_retained_inputs(tmp_path):
    w, store, collector, _, _ = service(tmp_path / "runs.sqlite3")
    try:
        await run(w, snapshot(channels=False))
        original = await w.get_session("run")
        original_item = next(p for p in original.progress if p.stage == "collect")
        original_content = await w.session_view.get_phase_content("run", "collect", version=original.version)
        _, _, _, entry = await w._recovery_material("run", stage="analyze")
        await w.resume("run", stage="collect")
        await w.wait("run")
        newest = await w.get_session("run")
        assert next(p for p in newest.progress if p.stage == "collect").result_ref != original_item.result_ref
        blocker = AI(block="first")
        w.ai_service = blocker
        await w.resume("run", stage="analyze", checkpoint_id=entry.config["configurable"]["checkpoint_id"])
        await blocker.started.wait()
        selected = await w.get_session("run")
        item = next(p for p in selected.progress if p.stage == "collect")
        assert item.result_ref == original_item.result_ref and item.version == original_item.version
        assert item.execution_epoch == selected.execution_epoch
        content = await w.session_view.get_phase_content("run", "collect", version=selected.version)
        assert content.content == original_content.content
        assert content.availability == original_content.availability == "available"
        assert len(collector.calls) == 2
        await w.cancel("run")
        await w.wait("run")
        assert await w.get_session("run", version=newest.version) == newest
    finally:
        await close(w, store)


async def test_child_checkpoint_and_incompatible_graph_are_rejected(tmp_path):
    blocker = AI(block="first")
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3", ai=blocker)
    try:
        await w.trigger(snapshot(channels=False), session_id="run")
        await blocker.started.wait()
        await w.cancel("run")
        await w.wait("run")
        child = next(cp for cp in [cp async for cp in w._checkpointer.alist(None)]
                     if cp.config["configurable"]["checkpoint_ns"].startswith("analyze:"))
        with pytest.raises(LogAgentError) as error:
            await w.resume("run", stage="analyze",
                           checkpoint_id=child.config["configurable"]["checkpoint_id"])
        assert error.value.code == "stage_unavailable"
        _, _, graph, saved = await w._recovery_material("run")
        await graph.aupdate_state(saved.config, {"graph_revision": "obsolete"})
        eligibility = await w.recovery_availability("run")
        assert not eligibility.available and eligibility.reason.code == "checkpoint_incompatible"
    finally:
        await close(w, store)
