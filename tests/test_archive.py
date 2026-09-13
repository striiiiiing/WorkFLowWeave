import asyncio
import hashlib
import json
import os
import shutil
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from logagent.archive import ArchiveReader, FileArchiveReader
from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    AnalysisArtifact,
    AnalysisResult,
    AnalysisTask,
    ArtifactInfo,
    BackupPolicy,
    ChannelConfig,
    CollectionArtifact,
    CollectionResult,
    DeliveryResult,
    ErrorInfo,
    FinalArtifact,
    Notification,
    SessionArchiveEnvelope,
    SessionRecord,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def make_snapshot(workflow_id="workflow", *, tasks=("analysis",), channels=("target",)):
    definition = WorkflowDefinition(
        id=workflow_id,
        sources=["source"],
        analyses=[AnalysisTask(id=task, ai="ai") for task in tasks],
        channels=list(channels),
    )
    return WorkflowSnapshot(
        workflow=definition,
        sources={"source": SourceConfig(id="source", collector="mock")},
        ai={"ai": AIConfig(id="ai")},
        channels={channel: ChannelConfig(id=channel, channel="mock") for channel in channels},
        created_at=NOW,
    )


def json_bytes(value):
    if isinstance(value, bytes):
        return value
    if hasattr(value, "model_dump_json"):
        return value.model_dump_json().encode("utf-8")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def save_envelope(data_dir, envelope):
    path = Path(data_dir) / "sessions" / envelope.record.id / "record.json"
    path.write_bytes(json_bytes(envelope))


def write_session(
    data_dir,
    session_id="session",
    *,
    workflow_id="workflow",
    status="completed",
    created_at=NOW,
    bodies=None,
    backup=None,
    frozen=True,
    analysis_statuses=None,
):
    """Prepare existing files as fixtures, without introducing an ArchiveStore."""
    snapshot = make_snapshot(workflow_id)
    if bodies is None:
        bodies = {
            "snapshot": snapshot,
            "collection": CollectionArtifact(
                shared_input="private source body",
                results=[
                    CollectionResult(
                        source_id="source", status="success", count=1, text="private source body"
                    )
                ],
            ),
            "analysis": AnalysisArtifact(
                order=["analysis"],
                results=[
                    AnalysisResult(task_id="analysis", status="success", text="analysis body")
                ],
            ),
            "final": FinalArtifact(
                outputs=[
                    Notification(session_id=session_id, output_id="analysis", text="final body")
                ]
            ),
        }
    directory = Path(data_dir) / "sessions" / session_id
    directory.mkdir(parents=True)
    indices = {}
    for name, body in bodies.items():
        raw = json_bytes(body)
        (directory / f"{name}.json").write_bytes(raw)
        indices[name] = ArtifactInfo(
            sha256=hashlib.sha256(raw).hexdigest(), size=len(raw), written_at=NOW
        )
    snapshot_hash = (
        indices["snapshot"].sha256
        if "snapshot" in indices
        else hashlib.sha256(json_bytes(snapshot)).hexdigest()
    )
    envelope = SessionArchiveEnvelope(
        format_version=1,
        backup=backup or BackupPolicy(),
        snapshot_sha256=snapshot_hash,
        record=SessionRecord(
            id=session_id,
            workflow_id=workflow_id,
            status=status,
            created_at=created_at,
            updated_at=created_at,
            output_frozen=frozen,
            artifacts=indices,
            analysis_statuses=analysis_statuses or {},
        ),
    )
    save_envelope(data_dir, envelope)
    return envelope


def reader(data_dir, **kwargs):
    return FileArchiveReader(data_dir, clock=lambda: NOW, **kwargs)


async def test_reader_has_only_read_capabilities_and_does_not_create_directories(tmp_path):
    archive = reader(tmp_path / "absent")
    assert set(ArchiveReader.__dict__) >= {"get", "list", "load_artifact", "availability"}
    assert not any(hasattr(archive, name) for name in ("create", "update", "resume", "trigger"))
    assert await archive.list() == []
    assert not (tmp_path / "absent").exists()
    with pytest.raises(LogAgentError, match="记录不存在") as error:
        await archive.get("session")
    assert error.value.code == "session_not_found"


async def test_get_and_list_return_independent_records_without_reading_artifacts(tmp_path):
    write_session(tmp_path, status="running", frozen=False)
    directory = tmp_path / "sessions" / "session"
    (directory / "final.json").write_bytes(b"broken body")
    original = {path.name: path.read_bytes() for path in directory.iterdir()}
    archive = reader(tmp_path)
    record = await archive.get("session")
    record.errors.append(ErrorInfo(code="changed", message="caller change"))
    record.artifacts.clear()
    listed = await archive.list()
    assert listed[0].status == "running"
    assert listed[0].errors == []
    assert set(listed[0].artifacts) == {"snapshot", "collection", "analysis", "final"}
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == original


async def test_list_filters_sorts_and_supports_internal_unlimited_queries(tmp_path):
    write_session(tmp_path, "old", created_at=NOW - timedelta(days=1), bodies={})
    write_session(tmp_path, "same_a", bodies={})
    write_session(tmp_path, "same_z", bodies={})
    write_session(tmp_path, "other", workflow_id="different", bodies={})
    archive = reader(tmp_path)
    assert [item.id for item in await archive.list("workflow", limit=None)] == [
        "same_z",
        "same_a",
        "old",
    ]
    assert [item.id for item in await archive.list("workflow", limit=1)] == ["same_z"]
    assert [item.id for item in await archive.list("different")] == ["other"]


@pytest.mark.parametrize("limit", [True, "1", 0, -1, 1.0])
async def test_invalid_list_limits_are_rejected_before_reading(tmp_path, limit):
    with pytest.raises(LogAgentError) as error:
        await reader(tmp_path).list(limit=limit)
    assert error.value.code == "invalid_argument"


@pytest.mark.parametrize("session_id", ["../elsewhere", "a/b", "", "a\n", "a" * 81])
async def test_invalid_session_ids_never_become_paths(tmp_path, session_id):
    with pytest.raises(LogAgentError) as error:
        await reader(tmp_path).get(session_id)
    assert error.value.code == "invalid_argument"


@pytest.mark.parametrize("name", ["../record", "record", "/tmp/private", "final.json"])
async def test_artifact_names_are_fixed(tmp_path, name):
    with pytest.raises(LogAgentError) as error:
        await reader(tmp_path).load_artifact("session", name)
    assert error.value.code == "invalid_argument"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(format_version=2),
        lambda data: data.pop("format_version"),
        lambda data: data.update(unknown="private-value"),
        lambda data: data["record"].update(id="other"),
        lambda data: data["record"].update(created_at="2026-09-13T12:00:00"),
        lambda data: data["record"].update(status="not-real"),
    ],
)
async def test_record_version_structure_and_identity_are_validated(tmp_path, mutate):
    envelope = write_session(tmp_path)
    data = envelope.model_dump(mode="json")
    mutate(data)
    (tmp_path / "sessions" / "session" / "record.json").write_bytes(json_bytes(data))
    with pytest.raises(LogAgentError) as error:
        await reader(tmp_path).get("session")
    assert error.value.code == "archive_corrupt"
    assert "private-value" not in error.value.info.model_dump_json()


async def test_corrupt_record_is_not_silently_omitted_from_list(tmp_path):
    write_session(tmp_path)
    (tmp_path / "sessions" / "session" / "record.json").write_bytes(b"{")
    with pytest.raises(LogAgentError) as error:
        await reader(tmp_path).list()
    assert error.value.code == "archive_corrupt"


async def test_initially_missing_sessions_root_is_an_empty_list(tmp_path):
    assert tmp_path.is_dir()
    archive = reader(tmp_path)
    assert not archive.sessions_dir.exists()
    assert await archive.list("workflow", limit=None) == []
    assert not archive.sessions_dir.exists()


@pytest.mark.parametrize("remove_root", [False, True])
async def test_record_disappearing_during_list_is_not_an_empty_archive(
    tmp_path, monkeypatch, remove_root
):
    write_session(tmp_path)
    archive = reader(tmp_path)
    original_open = os.open

    def remove_before_record_open(path, *args, **kwargs):
        if path == "record.json":
            if remove_root:
                shutil.rmtree(archive.sessions_dir)
            else:
                (archive.sessions_dir / "session" / "record.json").unlink()
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", remove_before_record_open)
    with pytest.raises(LogAgentError) as error:
        await archive.list("workflow", limit=None)
    assert error.value.code == "session_not_found"
    assert error.value.details["session_id"] == "session"
    assert archive.sessions_dir.exists() is not remove_root


async def test_root_that_is_a_file_is_an_error(tmp_path):
    (tmp_path / "sessions").write_text("not a directory")
    with pytest.raises(LogAgentError) as error:
        await reader(tmp_path).list()
    assert error.value.code == "archive_corrupt"


async def test_broken_root_symlink_is_not_treated_as_an_empty_archive(tmp_path):
    (tmp_path / "sessions").symlink_to(tmp_path / "absent", target_is_directory=True)
    with pytest.raises(LogAgentError) as error:
        await reader(tmp_path).list()
    assert error.value.code == "archive_corrupt"


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("snapshot", WorkflowSnapshot),
        ("collection", CollectionArtifact),
        ("analysis", AnalysisArtifact),
        ("final", FinalArtifact),
    ],
)
async def test_load_returns_strict_independent_typed_artifacts(tmp_path, name, model):
    write_session(tmp_path)
    archive = reader(tmp_path)
    artifact = await archive.load_artifact("session", name)
    assert isinstance(artifact, model)
    previous = artifact.model_dump()
    if name == "snapshot":
        artifact.sources.clear()
    elif name in ("collection", "analysis"):
        artifact.results.clear()
    else:
        artifact.outputs.clear()
    assert (await archive.load_artifact("session", name)).model_dump() == previous


@pytest.mark.parametrize(
    "reason",
    ["disabled", "out_of_scope", "not_created", "missing", "expired", "corrupt", "write_failed"],
)
async def test_all_artifact_unavailability_reasons_remain_distinct(tmp_path, reason):
    envelope = write_session(tmp_path)
    if reason == "disabled":
        envelope.backup.enabled = False
    elif reason == "out_of_scope":
        envelope.backup.stages = ["snapshot"]
    elif reason == "not_created":
        del envelope.record.artifacts["final"]
    elif reason == "missing":
        (tmp_path / "sessions" / "session" / "final.json").unlink()
    elif reason == "expired":
        envelope.record.artifacts["final"].expires_at = NOW
    elif reason == "corrupt":
        (tmp_path / "sessions" / "session" / "final.json").write_text("different")
    else:
        envelope.record.missing_artifacts["final"] = "write_failed"
    save_envelope(tmp_path, envelope)
    archive = reader(tmp_path)
    with pytest.raises(LogAgentError) as error:
        await archive.load_artifact("session", "final")
    assert error.value.code == "artifact_unavailable"
    assert error.value.details["reason"] == reason
    assert error.value.details["session_id"] == "session"
    assert error.value.details["artifact"] == "final"
    assert "final body" not in error.value.info.model_dump_json()
    assert (await archive.availability("session")).missing_artifacts["final"] == reason


async def test_retention_policy_expiration_is_checked_even_without_explicit_date(tmp_path):
    envelope = write_session(tmp_path, backup=BackupPolicy(retention_days=0.5))
    envelope.record.artifacts["final"].written_at = NOW - timedelta(hours=12)
    save_envelope(tmp_path, envelope)
    with pytest.raises(LogAgentError) as error:
        await reader(tmp_path).load_artifact("session", "final")
    assert error.value.details["reason"] == "expired"


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("collection", b'{"shared_input":"secret-body","results":[],"extra":1}'),
        ("collection", b'{"shared_input":"a","shared_input":"b","results":[]}'),
        ("collection", b'{"shared_input":"x","results":[],"value":NaN}'),
        ("collection", b"\xff"),
        (
            "analysis",
            {
                "order": ["one"],
                "results": [{"task_id": "other", "status": "success", "text": "secret-body"}],
            },
        ),
        ("analysis", {"order": ["one", "one"], "results": []}),
        (
            "final",
            {"outputs": [{"session_id": "other", "output_id": "one", "text": "secret-body"}]},
        ),
        (
            "final",
            {
                "outputs": [
                    {"session_id": "session", "output_id": "one", "text": "a"},
                    {"session_id": "session", "output_id": "one", "text": "b"},
                ]
            },
        ),
        ("snapshot", make_snapshot("another-workflow")),
    ],
)
async def test_indexed_bytes_still_require_valid_json_models_and_ownership(tmp_path, name, body):
    write_session(tmp_path, bodies={name: body})
    with pytest.raises(LogAgentError) as error:
        await reader(tmp_path).load_artifact("session", name)
    assert error.value.details["reason"] == "corrupt"
    assert "secret-body" not in error.value.info.model_dump_json()


@pytest.mark.parametrize("mutation", ["size", "digest", "snapshot_digest"])
async def test_index_size_hash_and_snapshot_identity_are_checked(tmp_path, mutation):
    envelope = write_session(tmp_path)
    if mutation == "size":
        envelope.record.artifacts["snapshot"].size += 1
    elif mutation == "digest":
        envelope.record.artifacts["snapshot"].sha256 = "0" * 64
    else:
        envelope.snapshot_sha256 = "0" * 64
    save_envelope(tmp_path, envelope)
    with pytest.raises(LogAgentError) as error:
        await reader(tmp_path).load_artifact("session", "snapshot")
    assert error.value.details["reason"] == "corrupt"


async def test_record_and_artifact_size_limits_are_enforced(tmp_path):
    write_session(tmp_path)
    with pytest.raises(LogAgentError) as record_error:
        await reader(tmp_path, max_record_bytes=8).get("session")
    assert record_error.value.code == "archive_corrupt"
    with pytest.raises(LogAgentError) as artifact_error:
        await reader(tmp_path, max_artifact_bytes=8).load_artifact("session", "final")
    assert artifact_error.value.details["cause"] == "size_limit"


async def test_growing_or_mismatched_file_cannot_force_unbounded_read(tmp_path):
    write_session(tmp_path)
    path = tmp_path / "sessions" / "session" / "final.json"
    with path.open("r+b") as file:
        file.truncate(1024 * 1024 * 1024)
    with pytest.raises(LogAgentError) as error:
        await reader(tmp_path, max_artifact_bytes=1024).load_artifact("session", "final")
    assert error.value.details["cause"] == "size_limit"


async def test_session_and_artifact_symlinks_cannot_escape_root(tmp_path):
    data_dir = tmp_path / "data"
    outside = tmp_path / "outside"
    write_session(outside)
    (data_dir / "sessions").mkdir(parents=True)
    (data_dir / "sessions" / "session").symlink_to(
        outside / "sessions" / "session", target_is_directory=True
    )
    with pytest.raises(LogAgentError) as error:
        await reader(data_dir).get("session")
    assert error.value.code == "archive_corrupt"
    (data_dir / "sessions" / "session").unlink()
    write_session(data_dir)
    target = data_dir / "sessions" / "session" / "final.json"
    target.unlink()
    target.symlink_to(outside / "sessions" / "session" / "final.json")
    with pytest.raises(LogAgentError) as error:
        await reader(data_dir).load_artifact("session", "final")
    assert error.value.details["reason"] == "corrupt"


async def test_filesystem_io_runs_off_the_event_loop_and_errors_are_redacted(tmp_path, monkeypatch):
    write_session(tmp_path)
    main_thread = threading.get_ident()
    calls = []
    original = os.open

    def tracked_open(path, *args, **kwargs):
        calls.append(threading.get_ident())
        if path == "final.json":
            raise PermissionError("secret-body /private/location")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", tracked_open)
    archive = reader(tmp_path)
    await archive.get("session")
    with pytest.raises(LogAgentError) as error:
        await archive.load_artifact("session", "final")
    assert calls and main_thread not in calls
    assert error.value.code == "archive_unavailable"
    assert "secret-body" not in error.value.info.model_dump_json()
    assert "/private/location" not in error.value.info.model_dump_json()


async def test_frozen_recovery_needs_only_snapshot_final_and_pending_receipts(tmp_path):
    envelope = write_session(tmp_path, status="partial")
    for name in ("collection", "analysis"):
        envelope.record.artifacts.pop(name)
        (tmp_path / "sessions" / "session" / f"{name}.json").unlink()
    save_envelope(tmp_path, envelope)
    result = await reader(tmp_path).availability("session")
    assert result.available == ["snapshot", "final"]
    assert result.recoverable is True


@pytest.mark.parametrize("status", ["success", "uncertain", "skipped"])
async def test_frozen_recovery_does_not_hint_at_repeating_completed_or_uncertain_sends(
    tmp_path, status
):
    envelope = write_session(tmp_path, status="partial")
    receipt = DeliveryResult(
        channel_id="target",
        output_id="analysis",
        status="failed" if status == "uncertain" else status,
        attempts=0 if status == "skipped" else 1,
        error=ErrorInfo(code="delivery", message="uncertain", details={"delivery_uncertain": True})
        if status == "uncertain"
        else None,
    )
    envelope.record.deliveries = [receipt]
    save_envelope(tmp_path, envelope)
    assert (await reader(tmp_path).availability("session")).recoverable is False


@pytest.mark.parametrize("status", ["created", "running", "completed"])
async def test_active_and_completed_records_are_not_recovery_candidates(tmp_path, status):
    write_session(tmp_path, status=status)
    assert (await reader(tmp_path).availability("session")).recoverable is False


@pytest.mark.parametrize("missing", ["snapshot", "collection", "analysis"])
async def test_unfrozen_recovery_requires_original_input_and_successful_analysis_bodies(
    tmp_path, missing
):
    envelope = write_session(
        tmp_path, status="failed", frozen=False, analysis_statuses={"analysis": "success"}
    )
    envelope.record.artifacts.pop(missing)
    save_envelope(tmp_path, envelope)
    assert (await reader(tmp_path).availability("session")).recoverable is False


async def test_unfrozen_recovery_can_use_input_before_any_successful_analysis(tmp_path):
    envelope = write_session(tmp_path, status="failed", frozen=False)
    envelope.record.artifacts.pop("analysis")
    save_envelope(tmp_path, envelope)
    result = await reader(tmp_path).availability("session")
    assert result.recoverable is True
    assert (await reader(tmp_path).get("session")).recoverable is False


async def test_concurrent_queries_do_not_share_mutable_objects_or_write_files(tmp_path):
    write_session(tmp_path)
    archive = reader(tmp_path)
    results = await asyncio.gather(*(archive.load_artifact("session", "final") for _ in range(10)))
    results[0].outputs.clear()
    assert all(len(result.outputs) == 1 for result in results[1:])
    assert set(path.name for path in (tmp_path / "sessions" / "session").iterdir()) == {
        "record.json",
        "snapshot.json",
        "collection.json",
        "analysis.json",
        "final.json",
    }
