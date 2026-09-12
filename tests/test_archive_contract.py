"""Failure and concurrency acceptance tests for the ArchiveStore contract."""

import asyncio
import os
import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import logagent.archive as archive_module
from logagent.archive import ArchiveStore
from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    AnalysisResult,
    AnalysisTask,
    BackupPolicy,
    ChannelConfig,
    CollectionResult,
    DeliveryResult,
    ErrorInfo,
    FanInConfig,
    Notification,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)


def snapshot(backup: BackupPolicy) -> WorkflowSnapshot:
    workflow = WorkflowDefinition(
        id="workflow",
        sources=["source"],
        analyses=[AnalysisTask(id="summary", ai="model")],
        channels=["notice"],
        backup=backup,
    )
    return WorkflowSnapshot(
        workflow=workflow,
        sources={"source": SourceConfig(id="source", collector="mock")},
        ai={"model": AIConfig(id="model")},
        channels={"notice": ChannelConfig(id="notice", channel="file", options={"path": "unused.md"})},
    )


async def create_session(store: ArchiveStore, backup: BackupPolicy | None = None):
    backup = backup if backup is not None else BackupPolicy()
    return await store.create("workflow", snapshot(backup), backup)


def collection(text: str) -> dict:
    result = CollectionResult(
        source_id="source",
        status="success",
        items=[{"text": text}],
        text=text,
        count=1,
        selected_count=1,
    )
    return {"shared_input": text, "results": [result.model_dump(mode="json")]}


def analysis(text: str) -> dict:
    result = AnalysisResult(task_id="summary", status="success", text=text)
    return {"order": ["summary"], "results": [result.model_dump(mode="json")], "events": []}


def final(session_id: str, text: str = "原始发布内容") -> dict:
    notification = Notification(session_id=session_id, output_id="summary", title="Report", text=text)
    return {"outputs": [notification.model_dump(mode="json")], "fan_in": None}


@pytest.fixture
def clock(monkeypatch):
    current = [datetime(2026, 9, 1, tzinfo=UTC)]
    monkeypatch.setattr(archive_module, "utc_now", lambda: current[0])
    return current


def block_replace(monkeypatch, target: Path):
    """Pause one file's commit until the test releases its worker thread."""
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    original = os.replace

    def delayed(source, destination, *args, **kwargs):
        if Path(destination) == target and not release.is_set():
            loop.call_soon_threadsafe(started.set)
            if not release.wait(10):
                raise TimeoutError("test did not release the blocked archive write")
        return original(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", delayed)
    return started, release


async def assert_unavailable(store, session_id, name, reason):
    with pytest.raises(LogAgentError) as error:
        await store.load_artifact(session_id, name)
    assert error.value.code == "ARTIFACT_UNAVAILABLE"
    assert error.value.details["session_id"] == session_id
    assert error.value.details["name"] == name
    assert error.value.details["reason"] == reason


async def test_content_replace_failure_keeps_previous_bytes_and_other_artifacts(tmp_path, monkeypatch):
    store = ArchiveStore(tmp_path)
    record = await create_session(store)
    previous = collection("previous input")
    await store.save_artifact(record.id, "collection", previous)
    other_stage = analysis("saved analysis")
    await store.save_artifact(record.id, "analysis", other_stage)
    original_snapshot = await store.load_artifact(record.id, "snapshot")
    target = tmp_path / record.id / "collection.json"
    old_bytes = target.read_bytes()
    old_index = (await store.get(record.id)).artifacts["collection"]
    original = os.replace

    def fail_content(source, destination, *args, **kwargs):
        if Path(destination) == target:
            raise OSError("injected content commit failure")
        return original(source, destination, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_content)
        with pytest.raises(LogAgentError) as error:
            await store.save_artifact(record.id, "collection", collection("new input"))
    assert error.value.code == "ARTIFACT_WRITE_FAILED"
    assert target.read_bytes() == old_bytes
    refreshed = await store.get(record.id)
    retained_index = refreshed.artifacts.get("collection")
    assert retained_index is None or retained_index.sha256 == old_index.sha256
    assert refreshed.missing_artifacts["collection"] == "write_failed"
    assert refreshed.errors
    assert await store.load_artifact(record.id, "analysis") == other_stage
    assert await store.load_artifact(record.id, "snapshot") == original_snapshot
    assert not list(target.parent.glob("*.tmp"))


@pytest.mark.parametrize("has_previous", [False, True], ids=["orphan", "stale-index"])
async def test_record_commit_failure_never_accepts_unindexed_content(tmp_path, monkeypatch, has_previous):
    store = ArchiveStore(tmp_path)
    record = await create_session(store)
    if has_previous:
        await store.save_artifact(record.id, "collection", collection("previous input"))
    await store.update(record.id, status="partial", stage="analyze")
    before = await store.get(record.id)
    target = tmp_path / record.id / "record.json"
    original = os.replace

    def fail_record(source, destination, *args, **kwargs):
        if Path(destination) == target:
            raise OSError("injected index commit failure")
        return original(source, destination, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_record)
        with pytest.raises(LogAgentError) as error:
            await store.save_artifact(record.id, "collection", collection("uncommitted index input"))
    assert error.value.code == "ARCHIVE_UNAVAILABLE"

    restarted = ArchiveStore(tmp_path)
    after = await restarted.get(record.id)
    assert after.artifacts.get("collection") == before.artifacts.get("collection")
    with pytest.raises(LogAgentError) as unavailable:
        await restarted.load_artifact(record.id, "collection")
    assert unavailable.value.code == "ARTIFACT_UNAVAILABLE"
    expected = {"corrupt", "write_failed"} if has_previous else {"not_created", "write_failed"}
    assert unavailable.value.details["reason"] in expected
    availability = await restarted.availability(record.id)
    assert "collection" not in availability["available"]
    assert availability["recoverable"] is False
    assert "snapshot" in availability["available"]


async def test_read_waits_for_the_content_and_index_commit(tmp_path, monkeypatch):
    store = ArchiveStore(tmp_path)
    record = await create_session(store)
    await store.save_artifact(record.id, "collection", collection("old"))
    started, release = block_replace(monkeypatch, tmp_path / record.id / "record.json")
    replacement = collection("new")
    writer = asyncio.create_task(store.save_artifact(record.id, "collection", replacement))
    reader = None
    try:
        await asyncio.wait_for(started.wait(), 3)
        reader = asyncio.create_task(store.load_artifact(record.id, "collection"))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(reader), 0.05)
    finally:
        release.set()
        await asyncio.gather(writer, *([reader] if reader is not None else []), return_exceptions=True)
    assert writer.result() is True
    assert reader is not None and reader.result() == replacement


@pytest.mark.parametrize("commit_name", ["collection.json", "record.json"], ids=["content", "index"])
async def test_cancelled_commit_keeps_session_lock_but_not_other_sessions(tmp_path, monkeypatch, commit_name):
    store = ArchiveStore(tmp_path)
    record = await create_session(store)
    independent = await create_session(store)
    await store.save_artifact(record.id, "collection", collection("initial"))
    started, release = block_replace(monkeypatch, tmp_path / record.id / commit_name)
    slow = asyncio.create_task(store.save_artifact(record.id, "collection", collection("slow")))
    newer = None
    try:
        await asyncio.wait_for(started.wait(), 3)
        slow.cancel()
        await asyncio.sleep(0)
        slow.cancel()
        newer = asyncio.create_task(store.save_artifact(record.id, "collection", collection("newest")))
        assert (
            await asyncio.wait_for(store.save_artifact(independent.id, "collection", collection("independent")), 2)
            is True
        )
        assert not newer.done(), "the cancelled worker released its session lock before finishing"
    finally:
        release.set()
        await asyncio.gather(slow, *([newer] if newer is not None else []), return_exceptions=True)
    assert slow.cancelled()
    assert newer is not None and newer.result() is True
    assert await store.load_artifact(record.id, "collection") == collection("newest")
    assert await store.load_artifact(independent.id, "collection") == collection("independent")


async def test_frozen_final_is_idempotent_and_cannot_be_rewritten_or_unfrozen(tmp_path):
    store = ArchiveStore(tmp_path)
    record = await create_session(store)
    original = final(record.id)
    await store.save_artifact(record.id, "final", original)
    await store.update(record.id, output_frozen=True, stage="notify", status="partial")
    reordered = {"fan_in": None, "outputs": [dict(reversed(list(original["outputs"][0].items())))]}
    assert await store.save_artifact(record.id, "final", reordered) is True

    with pytest.raises(LogAgentError):
        await store.save_artifact(record.id, "final", final(record.id, "different meaning"))
    with pytest.raises(LogAgentError):
        await store.update(record.id, output_frozen=False)
    assert (await store.get(record.id)).output_frozen is True
    assert await store.load_artifact(record.id, "final") == original
    assert await ArchiveStore(tmp_path).load_artifact(record.id, "final") == original


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
async def test_frozen_final_cannot_be_repaired_by_resubmitting_unverified_content(tmp_path, damage):
    store = ArchiveStore(tmp_path)
    record = await create_session(store)
    original = final(record.id)
    await store.save_artifact(record.id, "final", original)
    await store.update(record.id, output_frozen=True, stage="notify", status="partial")
    target = tmp_path / record.id / "final.json"
    if damage == "missing":
        target.unlink()
    else:
        target.write_text('{"not": "the original final"}', encoding="utf-8")
    damaged_bytes = target.read_bytes() if target.exists() else None

    with pytest.raises(LogAgentError):
        await store.save_artifact(record.id, "final", deepcopy(original))
    assert (target.read_bytes() if target.exists() else None) == damaged_bytes
    await assert_unavailable(store, record.id, "final", damage)
    assert (await store.availability(record.id))["recoverable"] is False


async def test_ttl_uses_each_artifacts_written_at_and_expires_at_is_exclusive(tmp_path, clock):
    store = ArchiveStore(tmp_path)
    record = await create_session(store, BackupPolicy(retention_days=1))
    origin = clock[0]
    clock[0] = origin + timedelta(hours=12)
    await store.save_artifact(record.id, "collection", collection("later stage"))
    await store.update(record.id, status="partial", stage="analyze")
    stored = await store.get(record.id)
    assert stored.artifacts["snapshot"].expires_at == origin + timedelta(days=1)
    assert stored.artifacts["collection"].expires_at == origin + timedelta(hours=36)

    clock[0] = origin + timedelta(days=1) - timedelta(microseconds=1)
    assert {"snapshot", "collection"} <= set((await store.availability(record.id))["available"])
    clock[0] = origin + timedelta(days=1)
    assert (tmp_path / record.id / "snapshot.json").exists()
    await assert_unavailable(store, record.id, "snapshot", "expired")
    assert await store.load_artifact(record.id, "collection") == collection("later stage")
    assert (await store.availability(record.id))["recoverable"] is False
    await store.expire()
    assert not (tmp_path / record.id / "snapshot.json").exists()
    assert (tmp_path / record.id / "collection.json").exists()

    clock[0] = origin + timedelta(hours=36)
    await assert_unavailable(store, record.id, "collection", "expired")
    await store.expire()
    assert not (tmp_path / record.id / "collection.json").exists()
    assert (await store.get(record.id)).id == record.id


@pytest.mark.parametrize("status", ["created", "running"])
async def test_active_sessions_keep_expired_by_clock_content_until_they_end(tmp_path, clock, status):
    store = ArchiveStore(tmp_path)
    record = await create_session(store, BackupPolicy(retention_days=1))
    await store.save_artifact(record.id, "collection", collection("active input"))
    if status == "running":
        await store.update(record.id, status="running", stage="analyze")
    clock[0] += timedelta(days=2)
    await store.expire()
    assert {"snapshot", "collection"} <= set((await store.availability(record.id))["available"])
    assert await store.load_artifact(record.id, "collection") == collection("active input")

    await store.update(record.id, status="partial", stage="analyze")
    await assert_unavailable(store, record.id, "collection", "expired")
    await store.expire()
    assert not (tmp_path / record.id / "collection.json").exists()
    assert (await store.get(record.id)).status == "partial"


async def test_failed_expiry_delete_remains_expired_and_can_be_retried(tmp_path, monkeypatch, clock):
    store = ArchiveStore(tmp_path)
    record = await create_session(store, BackupPolicy(retention_days=1))
    await store.save_artifact(record.id, "collection", collection("expired input"))
    await store.update(record.id, status="partial", stage="analyze")
    clock[0] += timedelta(days=1)
    target = tmp_path / record.id / "collection.json"
    original = os.unlink
    failures = []

    def fail_delete(path, *args, **kwargs):
        if Path(path) == target:
            failures.append(path)
            raise PermissionError("injected cleanup failure")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", fail_delete)
        await store.expire()
    assert failures, "cleanup did not attempt to delete the expired content"
    assert target.exists()
    refreshed = await store.get(record.id)
    assert refreshed.missing_artifacts["collection"] == "expired"
    assert refreshed.errors
    await assert_unavailable(store, record.id, "collection", "expired")
    availability = await store.availability(record.id)
    assert "collection" not in availability["available"]
    assert availability["recoverable"] is False

    await store.expire()
    assert not target.exists()
    assert (await store.get(record.id)).missing_artifacts["collection"] == "expired"


async def test_expiry_rechecks_status_after_an_inflight_session_update(tmp_path, monkeypatch, clock):
    store = ArchiveStore(tmp_path)
    record = await create_session(store, BackupPolicy(retention_days=1))
    await store.save_artifact(record.id, "collection", collection("resume input"))
    await store.update(record.id, status="partial", stage="analyze")
    clock[0] += timedelta(days=1) - timedelta(microseconds=1)
    started, release = block_replace(monkeypatch, tmp_path / record.id / "record.json")
    resumed = asyncio.create_task(store.update(record.id, status="running"))
    cleanup = None
    try:
        await asyncio.wait_for(started.wait(), 3)
        clock[0] += timedelta(microseconds=1)
        cleanup = asyncio.create_task(store.expire())
        await asyncio.sleep(0.05)
        assert (tmp_path / record.id / "collection.json").exists()
    finally:
        release.set()
        await asyncio.gather(resumed, *([cleanup] if cleanup is not None else []), return_exceptions=True)
    assert resumed.result().status == "running"
    assert cleanup is not None
    cleanup.result()
    assert await store.load_artifact(record.id, "collection") == collection("resume input")
    assert {"snapshot", "collection"} <= set((await store.availability(record.id))["available"])


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
async def test_lost_model_fan_in_result_cannot_be_rerun_before_output_freeze(tmp_path, damage):
    store = ArchiveStore(tmp_path)
    backup = BackupPolicy()
    saved_snapshot = snapshot(backup)
    saved_snapshot.workflow.fan_in = FanInConfig(ai="model")
    record = await store.create("workflow", saved_snapshot, backup)
    await store.save_artifact(record.id, "collection", collection("original input"))
    await store.save_artifact(record.id, "analysis", analysis("completed branch"))
    await store.update(record.id, status="partial", stage="aggregate", analysis_statuses={"summary": "success"})
    final_result = final(record.id, "completed model fan-in")
    final_result["outputs"][0]["output_id"] = "fan_in"
    final_result["fan_in"] = AnalysisResult(
        task_id="fan_in", status="success", text="completed model fan-in"
    ).model_dump(mode="json")
    await store.save_artifact(record.id, "final", final_result)
    before = await store.get(record.id)
    assert before.output_frozen is False
    assert before.recoverable is True
    assert "final" in before.artifacts

    target = tmp_path / record.id / "final.json"
    if damage == "missing":
        target.unlink()
    else:
        target.write_text('{"fan_in": "damaged model result"}', encoding="utf-8")

    restarted = ArchiveStore(tmp_path)
    availability = await restarted.availability(record.id)
    assert {"snapshot", "collection", "analysis"} <= set(availability["available"])
    assert availability["missing_artifacts"]["final"] == damage
    assert availability["recoverable"] is False
    await assert_unavailable(restarted, record.id, "final", damage)


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
async def test_lost_indexed_analysis_cannot_be_rerun_before_status_summary_is_saved(tmp_path, damage):
    store = ArchiveStore(tmp_path)
    record = await create_session(store)
    await store.save_artifact(record.id, "collection", collection("original input"))
    await store.save_artifact(record.id, "analysis", analysis("completed branch"))
    before = await store.update(record.id, status="partial", stage="analyze")
    assert before.analysis_statuses == {}
    assert before.recoverable is True

    target = tmp_path / record.id / "analysis.json"
    if damage == "missing":
        target.unlink()
    else:
        target.write_text('{"results": "damaged branch result"}', encoding="utf-8")

    restarted = ArchiveStore(tmp_path)
    restored = await restarted.get(record.id)
    assert restored.analysis_statuses == {}
    assert "analysis" in restored.artifacts
    assert restored.missing_artifacts["analysis"] == damage
    assert restored.recoverable is False
    availability = await restarted.availability(record.id)
    assert {"snapshot", "collection"} <= set(availability["available"])
    assert availability["recoverable"] is False
    await assert_unavailable(restarted, record.id, "analysis", damage)


@pytest.mark.parametrize("kind", ["success", "uncertain"])
@pytest.mark.parametrize("mutation", ["remove", "status", "attempts", "error"])
async def test_successful_or_uncertain_delivery_receipts_cannot_be_rewritten(tmp_path, kind, mutation):
    store = ArchiveStore(tmp_path)
    record = await create_session(store)
    await store.save_artifact(record.id, "final", final(record.id))
    receipt = DeliveryResult(channel_id="notice", output_id="summary", status="success", attempts=1)
    if kind == "uncertain":
        receipt = DeliveryResult(
            channel_id="notice",
            output_id="summary",
            status="timeout",
            attempts=1,
            error=ErrorInfo(
                code="DELIVERY_TIMEOUT",
                message="The server may have accepted this notification",
                details={"delivery_uncertain": True},
            ),
        )
    await store.update(record.id, status="partial", stage="notify", output_frozen=True, deliveries=[receipt])
    restarted = ArchiveStore(tmp_path)
    changed = receipt.model_dump(mode="json")
    if mutation == "status":
        changed["status"] = "failed" if kind == "success" else "success"
    elif mutation == "attempts":
        changed["attempts"] = 2
    elif mutation == "error":
        changed["error"] = {
            "code": "REWRITTEN",
            "message": "Replacement receipt diagnostics",
            "details": {"delivery_uncertain": False},
        }
    replacements = [] if mutation == "remove" else [changed]

    with pytest.raises(LogAgentError) as error:
        await restarted.update(record.id, deliveries=replacements)
    assert error.value.code == "CONFLICT"
    assert (await restarted.get(record.id)).deliveries == [receipt]
    assert (await ArchiveStore(tmp_path).get(record.id)).deliveries == [receipt]
    assert (await restarted.update(record.id, deliveries=[receipt.model_dump(mode="json")])).deliveries == [receipt]


async def test_failed_delivery_can_succeed_and_new_receipts_can_be_added(tmp_path):
    store = ArchiveStore(tmp_path)
    backup = BackupPolicy()
    saved_snapshot = snapshot(backup)
    for channel_id in ("uncertain", "retry", "later"):
        saved_snapshot.workflow.channels.append(channel_id)
        saved_snapshot.channels[channel_id] = ChannelConfig(
            id=channel_id, channel="file", options={"path": f"unused-{channel_id}.md"}
        )
    record = await store.create("workflow", saved_snapshot, backup)
    await store.save_artifact(record.id, "final", final(record.id))
    successful = DeliveryResult(channel_id="notice", output_id="summary", status="success", attempts=1)
    uncertain = DeliveryResult(
        channel_id="uncertain",
        output_id="summary",
        status="timeout",
        attempts=1,
        error=ErrorInfo(code="DELIVERY_TIMEOUT", message="Acceptance unknown", details={"delivery_uncertain": True}),
    )
    failed = DeliveryResult(
        channel_id="retry",
        output_id="summary",
        status="failed",
        attempts=1,
        error=ErrorInfo(code="DELIVERY_FAILED", message="Connection refused", details={"delivery_uncertain": False}),
    )
    await store.update(
        record.id,
        status="partial",
        stage="notify",
        output_frozen=True,
        deliveries=[successful, uncertain, failed],
    )
    completed_retry = DeliveryResult(channel_id="retry", output_id="summary", status="success", attempts=2)
    additional = DeliveryResult(channel_id="later", output_id="summary", status="success", attempts=1)
    expected = [successful, uncertain, completed_retry, additional]
    updated = await ArchiveStore(tmp_path).update(record.id, deliveries=expected)
    assert updated.deliveries == expected
    assert (await ArchiveStore(tmp_path).get(record.id)).deliveries == expected


@pytest.mark.parametrize(
    ("fan_in", "recoverable"),
    [
        pytest.param(None, True, id="no-fan-in"),
        pytest.param(FanInConfig(), True, id="default-order"),
        pytest.param(FanInConfig(order=["summary"]), True, id="explicit-branches"),
        pytest.param(FanInConfig(ai="model"), True, id="model-default-order"),
        pytest.param(FanInConfig(order=["summary", "$input"]), False, id="includes-input"),
        pytest.param(FanInConfig(order=["$input"]), False, id="only-input"),
    ],
)
async def test_aggregate_needs_collection_only_when_fan_in_reads_shared_input(tmp_path, fan_in, recoverable):
    store = ArchiveStore(tmp_path)
    backup = BackupPolicy(stages=["snapshot", "analysis", "final"])
    saved_snapshot = snapshot(backup)
    saved_snapshot.workflow.fan_in = fan_in
    record = await store.create("workflow", saved_snapshot, backup)
    assert await store.save_artifact(record.id, "collection", collection("excluded input")) is False
    before = await store.update(
        record.id, status="partial", stage="aggregate", analysis_statuses={"summary": "success"}
    )
    assert before.recoverable is False

    await store.save_artifact(record.id, "analysis", analysis("completed branch"))
    restarted = ArchiveStore(tmp_path)
    availability = await restarted.availability(record.id)
    assert {"snapshot", "analysis"} <= set(availability["available"])
    assert availability["missing_artifacts"]["collection"] == "out_of_scope"
    assert availability["recoverable"] is recoverable
    assert not (tmp_path / record.id / "collection.json").exists()

    retrying_analysis = await restarted.update(record.id, stage="analyze")
    assert retrying_analysis.recoverable is False
    assert retrying_analysis.missing_artifacts["collection"] == "out_of_scope"


async def test_aggregate_with_shared_input_recovers_when_collection_becomes_available(tmp_path):
    store = ArchiveStore(tmp_path)
    backup = BackupPolicy()
    saved_snapshot = snapshot(backup)
    saved_snapshot.workflow.fan_in = FanInConfig(order=["summary", "$input"])
    record = await store.create("workflow", saved_snapshot, backup)
    await store.save_artifact(record.id, "analysis", analysis("completed branch"))
    before = await store.update(
        record.id, status="partial", stage="aggregate", analysis_statuses={"summary": "success"}
    )
    assert before.recoverable is False
    assert before.missing_artifacts["collection"] == "not_created"

    await store.save_artifact(record.id, "collection", collection("original shared input"))
    assert (await ArchiveStore(tmp_path).availability(record.id))["recoverable"] is True


@pytest.mark.parametrize("observer", ["get", "availability", "load_artifact"])
async def test_observed_expiry_survives_clock_rollback_and_store_restart(tmp_path, clock, observer):
    store = ArchiveStore(tmp_path)
    record = await create_session(store, BackupPolicy(retention_days=1))
    await store.save_artifact(record.id, "collection", collection("time-limited input"))
    await store.update(record.id, status="partial", stage="analyze")
    assert (await store.availability(record.id))["recoverable"] is True
    origin = clock[0]
    clock[0] = origin + timedelta(days=1)
    if observer == "load_artifact":
        await assert_unavailable(store, record.id, "collection", "expired")
    elif observer == "get":
        assert (await store.get(record.id)).missing_artifacts["collection"] == "expired"
    else:
        assert (await store.availability(record.id))["missing_artifacts"]["collection"] == "expired"

    clock[0] = origin + timedelta(hours=12)
    restarted = ArchiveStore(tmp_path)
    restored = await restarted.get(record.id)
    assert restored.missing_artifacts["collection"] == "expired"
    assert restored.recoverable is False
    await assert_unavailable(restarted, record.id, "collection", "expired")
    availability = await restarted.availability(record.id)
    assert "collection" not in availability["available"]
    assert availability["recoverable"] is False
    assert (tmp_path / record.id / "collection.json").exists()
