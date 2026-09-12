"""Session history, backup policy and recovery-material acceptance tests."""

import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from logagent import archive
from logagent.archive import ArchiveStore
from logagent.errors import LogAgentError
from logagent.models import (
    ARTIFACT_NAMES,
    AIConfig,
    AnalysisTask,
    BackupPolicy,
    ChannelConfig,
    FanInConfig,
    SessionRecord,
    SetterTemplate,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)


def make_snapshot(workflow_id="workflow"):
    return WorkflowSnapshot(
        workflow=WorkflowDefinition(
            id=workflow_id,
            sources=["source"],
            analyses=[AnalysisTask(id="summary", ai="model")],
            channels=["file"],
        ),
        sources={"source": SourceConfig(id="source", collector="mock", options={"items": [{"text": "original"}]})},
        ai={"model": AIConfig(id="model", api_key_env="EXAMPLE_KEY")},
        channels={"file": ChannelConfig(id="file", channel="file", options={"path": "/unused/report.md"})},
    )


def collection(text="original"):
    return {
        "shared_input": text,
        "results": [
            {
                "source_id": "source",
                "status": "success",
                "items": [{"text": text}],
                "text": text,
                "count": 1,
                "selected_count": 1,
            }
        ],
    }


def analysis():
    return {
        "order": ["summary"],
        "results": [{"task_id": "summary", "status": "success", "text": "summary"}],
        "events": [],
    }


def final(session_id):
    return {"outputs": [{"session_id": session_id, "output_id": "summary", "text": "report"}], "fan_in": None}


@pytest.mark.asyncio
async def test_round_trip_and_detached_results(tmp_path):
    store = ArchiveStore(tmp_path)
    snapshot = make_snapshot()
    original = snapshot.model_dump(mode="json")
    record = await store.create("workflow", snapshot, BackupPolicy())
    assert isinstance(record, SessionRecord)
    assert record.created_at.tzinfo is UTC
    assert record.updated_at >= record.created_at
    assert record.missing_artifacts == {name: "not_created" for name in ARTIFACT_NAMES if name != "snapshot"}
    assert record.recoverable is False
    snapshot.sources["source"].options["items"][0]["text"] = "newest source"
    await store.save_artifact(record.id, "collection", collection())
    await store.save_artifact(record.id, "analysis", analysis())
    await store.save_artifact(record.id, "final", final(record.id))
    await store.update(record.id, status="failed", stage="analyze", source_statuses={"source": "success"})

    restarted = ArchiveStore(tmp_path)
    assert await restarted.load_artifact(record.id, "snapshot") == original
    assert (await restarted.load_artifact(record.id, "collection"))["shared_input"] == "original"
    restored = await restarted.get(record.id)
    assert restored.status == "failed"
    assert restored.recoverable
    assert not restored.missing_artifacts
    restored.errors.clear()
    restored.source_statuses.clear()
    assert (await restarted.get(record.id)).source_statuses == {"source": "success"}
    loaded = await restarted.load_artifact(record.id, "collection")
    loaded["results"][0]["items"][0]["text"] = "caller change"
    assert (await restarted.load_artifact(record.id, "collection"))["results"][0]["items"][0]["text"] == "original"
    disk = json.loads((tmp_path / record.id / "record.json").read_text())
    assert disk["format_version"] == 1
    assert "backup" in disk and "record" in disk
    assert "shared_input" not in disk["record"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (BackupPolicy(enabled=False), dict.fromkeys(ARTIFACT_NAMES, "disabled")),
        (
            BackupPolicy(stages=["analysis"]),
            {
                "snapshot": "out_of_scope",
                "collection": "out_of_scope",
                "analysis": "not_created",
                "final": "out_of_scope",
            },
        ),
    ],
)
async def test_backups_do_not_control_record_lifetime(tmp_path, policy, expected):
    store = ArchiveStore(tmp_path)
    record = await store.create("workflow", make_snapshot(), policy)
    assert record.missing_artifacts == expected
    assert not await store.save_artifact(record.id, "collection", collection())
    for name, reason in expected.items():
        with pytest.raises(LogAgentError) as error:
            await store.load_artifact(record.id, name)
        assert error.value.code == "ARTIFACT_UNAVAILABLE"
        assert error.value.details["reason"] == reason
    await store.update(record.id, status="partial", stage="notify", output_frozen=True)
    restored = await ArchiveStore(tmp_path).get(record.id)
    assert restored.output_frozen
    assert restored.status == "partial"
    assert not restored.recoverable
    assert [path.name for path in (tmp_path / record.id).iterdir()] == ["record.json"]


@pytest.mark.asyncio
async def test_session_ids_queries_and_ties(tmp_path, monkeypatch):
    instant = datetime(2026, 9, 12, tzinfo=UTC)
    monkeypatch.setattr(archive, "utc_now", lambda: instant)
    store = ArchiveStore(tmp_path)
    assert await store.list() == []
    records = await asyncio.gather(
        *(store.create("workflow", make_snapshot(), BackupPolicy(enabled=False)) for _ in range(12))
    )
    assert len({record.id for record in records}) == 12
    ids = sorted((record.id for record in records), reverse=True)
    assert [record.id for record in await store.list(limit=None)] == ids
    assert [record.id for record in await store.list(limit=3)] == ids[:3]
    monkeypatch.setattr(archive, "utc_now", lambda: instant + timedelta(seconds=1))
    other = await store.create("other", make_snapshot("other"), BackupPolicy(enabled=False))
    assert (await store.list())[0].id == other.id
    assert len(await store.list(workflow_id="workflow")) == 12
    assert await store.list(workflow_id="absent") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, True, "3", 2.5])
async def test_list_rejects_invalid_limits(tmp_path, limit):
    with pytest.raises(LogAgentError) as error:
        await ArchiveStore(tmp_path).list(limit=limit)
    assert error.value.code == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_updates_merge_latest_fields_and_protect_store_metadata(tmp_path):
    store = ArchiveStore(tmp_path)
    record = await store.create("workflow", make_snapshot(), BackupPolicy())
    await asyncio.gather(
        store.update(record.id, status="running"),
        store.update(record.id, source_statuses={"source": "filtered_empty"}),
        store.update(record.id, analysis_statuses={"summary": "timeout"}),
    )
    current = await store.get(record.id)
    assert current.status == "running"
    assert current.source_statuses == {"source": "filtered_empty"}
    assert current.analysis_statuses == {"summary": "timeout"}
    for field in ("id", "workflow_id", "created_at", "updated_at", "artifacts", "recoverable", "missing_artifacts"):
        with pytest.raises(LogAgentError) as error:
            await store.update(record.id, **{field: None})
        assert error.value.code == "CONFLICT"
    for changes in ({"status": "pretend_success"}, {"unexpected": True}, {"output_frozen": "false"}):
        with pytest.raises(LogAgentError) as error:
            await store.update(record.id, **changes)
        assert error.value.code == "VALIDATION_ERROR"
    assert (await store.get(record.id)).status == "running"


@pytest.mark.asyncio
async def test_startup_marks_only_abandoned_running_sessions(tmp_path):
    store = ArchiveStore(tmp_path)
    running = await store.create("workflow", make_snapshot(), BackupPolicy())
    queued = await store.create("workflow", make_snapshot(), BackupPolicy())
    await store.save_artifact(running.id, "collection", collection())
    await store.update(running.id, status="running", stage="analyze")
    assert await store.mark_interrupted() == []
    restarted = ArchiveStore(tmp_path)
    assert (await restarted.get(running.id)).status == "running", "construction must not start a scan"
    interrupted = await restarted.mark_interrupted()
    assert [record.id for record in interrupted] == [running.id]
    assert interrupted[0].status == "interrupted"
    assert interrupted[0].stage == "analyze"
    assert interrupted[0].recoverable
    assert interrupted[0].errors[-1].code == "RUN_INTERRUPTED"
    assert (await restarted.get(queued.id)).status == "created"
    assert await restarted.mark_interrupted() == []


@pytest.mark.asyncio
async def test_create_keeps_record_when_snapshot_write_fails(tmp_path, monkeypatch):
    real_write = archive.atomic_write

    def fail_snapshot(path, data):
        if path.name == "snapshot.json":
            raise OSError("EXAMPLE_PRIVATE_DISK_DETAIL")
        return real_write(path, data)

    monkeypatch.setattr(archive, "atomic_write", fail_snapshot)
    store = ArchiveStore(tmp_path)
    record = await store.create("workflow", make_snapshot(), BackupPolicy())
    assert record.missing_artifacts["snapshot"] == "write_failed"
    assert record.errors[-1].code == "ARTIFACT_WRITE_FAILED"
    assert "EXAMPLE_PRIVATE_DISK_DETAIL" not in record.model_dump_json()
    assert not record.recoverable
    assert len(await store.list()) == 1


@pytest.mark.asyncio
async def test_record_write_failure_is_a_service_error(tmp_path, monkeypatch):
    def fail(path, data):
        raise OSError("example disk failure")

    monkeypatch.setattr(archive, "atomic_write", fail)
    with pytest.raises(LogAgentError) as error:
        await ArchiveStore(tmp_path).create("workflow", make_snapshot(), BackupPolicy())
    assert error.value.code == "ARCHIVE_UNAVAILABLE"
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "modified", "truncated", "bad_json", "bad_schema"])
async def test_artifact_reads_verify_bytes_and_required_structure(tmp_path, kind):
    store = ArchiveStore(tmp_path)
    record = await store.create("workflow", make_snapshot(), BackupPolicy())
    await store.save_artifact(record.id, "collection", collection())
    path = tmp_path / record.id / "collection.json"
    if kind == "missing":
        path.unlink()
    elif kind == "modified":
        path.write_bytes(path.read_bytes().replace(b"original", b"tampered"))
    elif kind == "truncated":
        path.write_bytes(path.read_bytes()[:10])
    else:
        raw = b"{" if kind == "bad_json" else b'{"shared_input": 2, "results": []}'
        path.write_bytes(raw)
        management = tmp_path / record.id / "record.json"
        data = json.loads(management.read_text())
        data["record"]["artifacts"]["collection"].update(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw))
        management.write_text(json.dumps(data))
    with pytest.raises(LogAgentError) as error:
        await store.load_artifact(record.id, "collection")
    assert error.value.details["reason"] == ("missing" if kind == "missing" else "corrupt")
    assert (await store.availability(record.id))["available"] == ["snapshot"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"format_version": 99}, "ARCHIVE_UNSUPPORTED_VERSION"),
        ({"format_version": True}, "ARCHIVE_CORRUPT"),
        ({"unexpected": True}, "ARCHIVE_CORRUPT"),
    ],
)
async def test_record_format_and_schema_are_validated(tmp_path, mutation, code):
    store = ArchiveStore(tmp_path)
    record = await store.create("workflow", make_snapshot(), BackupPolicy())
    path = tmp_path / record.id / "record.json"
    content = json.loads(path.read_text())
    content.update(mutation)
    path.write_text(json.dumps(content))
    with pytest.raises(LogAgentError) as error:
        await store.get(record.id)
    assert error.value.code == code


@pytest.mark.asyncio
async def test_invalid_artifacts_and_paths_do_not_create_files(tmp_path):
    store = ArchiveStore(tmp_path)
    with pytest.raises(LogAgentError) as error:
        await store.create("different", make_snapshot(), BackupPolicy())
    assert error.value.code == "VALIDATION_ERROR"
    record = await store.create("workflow", make_snapshot(), BackupPolicy())
    for name, content in (
        ("../../outside", {}),
        ("collection", {"shared_input": "input"}),
        ("analysis", {"order": [], "results": analysis()["results"], "events": []}),
        ("final", final("different")),
    ):
        with pytest.raises(LogAgentError) as error:
            await store.save_artifact(record.id, name, content)
        assert error.value.code == "VALIDATION_ERROR"
    for invalid in ("../outside", "", "has space"):
        with pytest.raises(LogAgentError):
            await store.get(invalid)
    with pytest.raises(LogAgentError) as error:
        await store.get("missing")
    assert error.value.code == "NOT_FOUND"
    assert sorted(path.name for path in (tmp_path / record.id).iterdir()) == ["record.json", "snapshot.json"]


@pytest.mark.asyncio
async def test_snapshot_cannot_be_replaced_with_current_resources(tmp_path):
    store = ArchiveStore(tmp_path)
    snapshot = make_snapshot()
    record = await store.create("workflow", snapshot, BackupPolicy())
    original = snapshot.model_dump(mode="json")
    assert await store.save_artifact(record.id, "snapshot", original)
    changed = deepcopy(original)
    changed["ai"]["model"]["model"] = "new-model"
    with pytest.raises(LogAgentError) as error:
        await store.save_artifact(record.id, "snapshot", changed)
    assert error.value.code == "CONFLICT"
    assert await store.load_artifact(record.id, "snapshot") == original


@pytest.mark.asyncio
async def test_recovery_requires_saved_successes_and_supports_frozen_outputs(tmp_path):
    store = ArchiveStore(tmp_path)
    record = await store.create("workflow", make_snapshot(), BackupPolicy())
    await store.update(record.id, status="failed", stage="analyze")
    assert not (await store.availability(record.id))["recoverable"]
    await store.save_artifact(record.id, "collection", collection())
    assert (await store.availability(record.id))["recoverable"]
    await store.update(record.id, analysis_statuses={"summary": "success"})
    assert not (await store.availability(record.id))["recoverable"]
    await store.save_artifact(record.id, "analysis", {"order": ["summary"], "results": [], "events": []})
    assert not (await store.availability(record.id))["recoverable"]
    await store.save_artifact(record.id, "analysis", analysis())
    assert (await store.availability(record.id))["recoverable"]
    await store.save_artifact(record.id, "final", final(record.id))
    await store.update(record.id, stage="notify", output_frozen=True)
    (tmp_path / record.id / "collection.json").unlink()
    (tmp_path / record.id / "analysis.json").unlink()
    await store.update(
        record.id, deliveries=[{"channel_id": "file", "output_id": "summary", "status": "success", "attempts": 1}]
    )
    availability = await ArchiveStore(tmp_path).availability(record.id)
    assert availability["recoverable"]
    assert availability["available"] == ["snapshot", "final"]
    assert (await store.get(record.id)).deliveries[0].status == "success"
    (tmp_path / record.id / "final.json").unlink()
    assert not (await store.availability(record.id))["recoverable"]


@pytest.mark.asyncio
async def test_expired_terminal_content_cannot_be_revived_by_status_update(tmp_path, monkeypatch):
    now = datetime(2026, 9, 12, tzinfo=UTC)
    monkeypatch.setattr(archive, "utc_now", lambda: now)
    store = ArchiveStore(tmp_path)
    record = await store.create("workflow", make_snapshot(), BackupPolicy(retention_days=0.5))
    await store.save_artifact(record.id, "collection", collection())
    await store.update(record.id, status="partial", stage="analyze")
    assert (await store.availability(record.id))["recoverable"]

    now += timedelta(hours=12)
    await store.update(record.id, status="running")
    restarted = ArchiveStore(tmp_path)
    for name in ("snapshot", "collection"):
        assert (tmp_path / record.id / (name + ".json")).is_file()
        with pytest.raises(LogAgentError) as error:
            await restarted.load_artifact(record.id, name)
        assert error.value.details["reason"] == "expired"
    with pytest.raises(LogAgentError) as error:
        await restarted.save_artifact(record.id, "collection", collection())
    assert error.value.details["reason"] == "expired"
    interrupted = await restarted.mark_interrupted()
    assert interrupted[0].status == "interrupted"
    assert not interrupted[0].recoverable
    assert (await restarted.availability(record.id))["available"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["analysis", "final"])
async def test_first_result_backup_failure_does_not_permit_rerunning_unknown_success(tmp_path, monkeypatch, name):
    store = ArchiveStore(tmp_path)
    snapshot = make_snapshot()
    snapshot.workflow.fan_in = FanInConfig(ai="model")
    record = await store.create("workflow", snapshot, BackupPolicy())
    await store.save_artifact(record.id, "collection", collection())
    if name == "final":
        await store.save_artifact(record.id, "analysis", analysis())
    stage = "analyze" if name == "analysis" else "aggregate"
    await store.update(record.id, status="failed", stage=stage)
    assert (await store.availability(record.id))["recoverable"]
    payload = analysis() if name == "analysis" else final(record.id)
    if name == "final":
        payload["fan_in"] = {"task_id": "fan_in", "status": "success", "text": "report"}
    real_write = archive.atomic_write

    def fail_body(path, data):
        if path.name == name + ".json":
            raise OSError("injected first backup failure")
        return real_write(path, data)

    monkeypatch.setattr(archive, "atomic_write", fail_body)
    with pytest.raises(LogAgentError) as error:
        await store.save_artifact(record.id, name, payload)
    assert error.value.code == "ARTIFACT_WRITE_FAILED"
    restored = await ArchiveStore(tmp_path).get(record.id)
    assert name not in restored.artifacts
    assert restored.analysis_statuses == {}
    assert restored.missing_artifacts[name] == "write_failed"
    assert not restored.recoverable


@pytest.mark.asyncio
async def test_archive_never_resolves_latest_resources(tmp_path):
    from logagent.config import ResourceStore

    resources = ResourceStore(tmp_path / "resources")
    await resources.save("sources", SourceConfig(id="source", collector="mock"))
    await resources.save("setters", SetterTemplate(id="unused", collector="mock"))
    await resources.save("ai", AIConfig(id="model", model="original"))
    definition = WorkflowDefinition(
        id="workflow", sources=["source"], analyses=[AnalysisTask(id="summary", ai="model")]
    )
    await resources.save("workflows", definition)
    store = ArchiveStore(tmp_path / "sessions")
    record = await store.create("workflow", await resources.snapshot("workflow"), BackupPolicy())
    await resources.save("ai", AIConfig(id="model", model="newest"))
    saved = WorkflowSnapshot.model_validate(await store.load_artifact(record.id, "snapshot"))
    assert saved.ai["model"].model == "original"
