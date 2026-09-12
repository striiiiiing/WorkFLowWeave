"""Persistent session records and independently verifiable stage backups."""

from __future__ import annotations

import asyncio
import hashlib
import json
import stat
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4
from weakref import WeakValueDictionary

from pydantic import Field, ValidationError, field_validator, model_validator

from logagent._io import atomic_write, json_bytes, read_json, run_io
from logagent.config import validate_id, validation_error
from logagent.errors import LogAgentError
from logagent.models import (
    ARTIFACT_NAMES,
    AnalysisResult,
    AnalysisStatus,
    ArtifactInfo,
    BackupPolicy,
    CollectionResult,
    DeliveryStatus,
    Identifier,
    Model,
    Notification,
    SessionRecord,
    SessionStatus,
    WorkflowSnapshot,
    unique,
    utc_now,
    validate_json_value,
)

FORMAT_VERSION = 1
ACTIVE_STATUSES = {SessionStatus.CREATED, SessionStatus.RUNNING}
RESUMABLE_STATUSES = {SessionStatus.FAILED, SessionStatus.PARTIAL, SessionStatus.CANCELLED, SessionStatus.INTERRUPTED}
STORE_FIELDS = {"id", "workflow_id", "created_at", "updated_at", "artifacts", "missing_artifacts", "recoverable"}


class _Envelope(Model):
    format_version: Annotated[int, Field(strict=True)]
    backup: BackupPolicy
    record: SessionRecord
    snapshot_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class _Collection(Model):
    shared_input: str
    results: list[CollectionResult]

    @model_validator(mode="after")
    def validate_sources(self):
        unique([result.source_id for result in self.results], "collection.results")
        return self


class _Analysis(Model):
    order: list[Identifier]
    results: list[AnalysisResult]
    events: list[dict[str, Any]]

    _json = field_validator("events", mode="before")(validate_json_value)

    @model_validator(mode="after")
    def validate_tasks(self):
        unique(self.order, "analysis.order")
        ids = unique([result.task_id for result in self.results], "analysis.results")
        if set(ids) - set(self.order):
            raise ValueError("Analysis results must refer to tasks in order")
        return self


class _Final(Model):
    outputs: list[Notification]
    fan_in: AnalysisResult | None

    @model_validator(mode="after")
    def validate_outputs(self):
        unique([output.output_id for output in self.outputs], "final.outputs")
        return self


_ARTIFACT_MODELS = {"snapshot": WorkflowSnapshot, "collection": _Collection, "analysis": _Analysis, "final": _Final}


def _content(name: str, value: Any, session_id: str, workflow_id: str) -> dict:
    model = _ARTIFACT_MODELS[name].model_validate(value)
    if name == "snapshot" and model.workflow.id != workflow_id:
        raise ValueError("Snapshot belongs to a different Workflow")
    if name == "final" and any(output.session_id != session_id for output in model.outputs):
        raise ValueError("Final output belongs to a different session")
    return model.model_dump(mode="json")


def _expires_at(written_at: datetime, backup: BackupPolicy) -> datetime | None:
    if backup.retention_days is None:
        return None
    try:
        return written_at + timedelta(days=backup.retention_days)
    except OverflowError as exc:
        raise LogAgentError(
            "VALIDATION_ERROR",
            "Retention exceeds the supported timestamp range",
            {"errors": [{"path": ["backup", "retention_days"], "reason": "Retention is too large"}]},
        ) from exc


class ArchiveStore:
    """One Store per service; no cross-process locking or background execution."""

    def __init__(self, root: str | Path):
        try:
            self.root = Path(root).resolve()
        except (OSError, ValueError, RuntimeError) as exc:
            raise LogAgentError("ARCHIVE_UNAVAILABLE", "Archive root is unavailable") from exc
        self._index_lock = asyncio.Lock()
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        self._active_ids: set[str] = set()

    def _lock(self, session_id: str) -> asyncio.Lock:
        validate_id(session_id)
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    def _path(self, session_id: str, filename: str = "record.json") -> Path:
        validate_id(session_id)
        directory = self.root / session_id
        path = directory / filename
        try:
            invalid = directory.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(directory)
        except (ValueError, RuntimeError) as exc:
            raise LogAgentError("ARCHIVE_UNAVAILABLE", "Archive path is invalid", {"session_id": session_id}) from exc
        if invalid:
            raise LogAgentError("ARCHIVE_UNAVAILABLE", "Archive path is invalid", {"session_id": session_id})
        return path

    @staticmethod
    def _name(name: str) -> str:
        if name not in ARTIFACT_NAMES:
            raise LogAgentError("VALIDATION_ERROR", "Unknown artifact name")
        return name

    async def _io(self, function, *args):
        try:
            return await run_io(function, *args)
        except OSError as exc:
            raise LogAgentError("ARCHIVE_UNAVAILABLE", "Archive storage is unavailable") from exc

    async def _operation(self, session_id: str, function, *args):
        async with self._lock(session_id):
            return await self._io(function, session_id, *args)

    def _read(self, session_id: str) -> _Envelope:
        path = self._path(session_id)
        try:
            if not stat.S_ISREG(path.stat().st_mode):
                raise LogAgentError(
                    "ARCHIVE_CORRUPT",
                    "Session record is not a regular file",
                    {"session_id": session_id},
                )
            value = read_json(path)
        except FileNotFoundError as exc:
            if path.parent.exists():
                raise LogAgentError(
                    "ARCHIVE_CORRUPT",
                    "Session record is missing",
                    {"session_id": session_id, "reason": "missing_record"},
                ) from exc
            raise LogAgentError("NOT_FOUND", "Session does not exist", {"session_id": session_id}) from exc
        except ValueError as exc:
            raise LogAgentError(
                "ARCHIVE_CORRUPT",
                "Session record JSON is invalid",
                {"session_id": session_id, "reason": "invalid_json"},
            ) from exc
        if (
            isinstance(value, dict)
            and type(value.get("format_version")) is int
            and value["format_version"] != FORMAT_VERSION
        ):
            raise LogAgentError(
                "ARCHIVE_UNSUPPORTED_VERSION",
                "Archive format version is unsupported",
                {"session_id": session_id},
            )
        try:
            envelope = _Envelope.model_validate(value)
        except ValidationError as exc:
            raise LogAgentError(
                "ARCHIVE_CORRUPT",
                "Session record schema is invalid",
                {"session_id": session_id, "reason": "invalid_schema"},
            ) from exc
        if envelope.record.id != session_id:
            raise LogAgentError(
                "ARCHIVE_CORRUPT",
                "Session ID does not match its directory",
                {"session_id": session_id, "reason": "id_mismatch"},
            )
        return envelope

    def _persist(self, envelope: _Envelope) -> None:
        envelope.record.updated_at = utc_now()
        atomic_write(self._path(envelope.record.id), json_bytes(envelope.model_dump(mode="json")))

    @staticmethod
    def _policy_reason(envelope: _Envelope, name: str) -> str | None:
        if not envelope.backup.enabled:
            return "disabled"
        if name not in envelope.backup.stages:
            return "out_of_scope"
        return None

    def _inspect(self, envelope: _Envelope, name: str, now: datetime) -> tuple[dict | None, str | None]:
        if reason := self._policy_reason(envelope, name):
            return None, reason
        record = envelope.record
        if record.missing_artifacts.get(name) in {"expired", "write_failed"}:
            return None, record.missing_artifacts[name]
        info = record.artifacts.get(name)
        if info is None:
            return None, "not_created"
        if record.status not in ACTIVE_STATUSES and info.expires_at is not None and now >= info.expires_at:
            return None, "expired"
        path = self._path(record.id, name + ".json")
        try:
            if not stat.S_ISREG(path.stat().st_mode):
                return None, "corrupt"
            raw = path.read_bytes()
        except FileNotFoundError:
            return None, "missing"
        if len(raw) != info.size or hashlib.sha256(raw).hexdigest() != info.sha256:
            return None, "corrupt"
        try:
            value = json.loads(raw)
            validate_json_value(value)
            content = _content(name, value, record.id, record.workflow_id)
        except ValueError:
            return None, "corrupt"
        if name == "snapshot" and hashlib.sha256(json_bytes(content)).hexdigest() != envelope.snapshot_sha256:
            return None, "corrupt"
        return content, None

    @staticmethod
    def _recoverable(record: SessionRecord, contents: dict[str, dict]) -> bool:
        if record.status not in RESUMABLE_STATUSES or "snapshot" not in contents:
            return False
        if record.output_frozen:
            return "final" in contents
        if record.stage in {"notify", "finish"}:
            return False
        fan_in = contents["snapshot"]["workflow"]["fan_in"]
        if (
            fan_in
            and fan_in["ai"]
            and "final" not in contents
            and ("final" in record.artifacts or record.missing_artifacts.get("final") == "write_failed")
        ):
            return False
        needs_input = record.stage != "aggregate" or (fan_in is not None and "$input" in fan_in["order"])
        if needs_input and "collection" not in contents:
            return False
        # A committed result can precede its summary update; losing it must not
        # silently permit rerunning a branch that may already have succeeded.
        if "analysis" not in contents and (
            "analysis" in record.artifacts or record.missing_artifacts.get("analysis") == "write_failed"
        ):
            return False
        successful = {key for key, status in record.analysis_statuses.items() if status == AnalysisStatus.SUCCESS}
        if successful or record.stage == "aggregate":
            if "analysis" not in contents:
                return False
            saved = {result["task_id"] for result in contents["analysis"]["results"] if result["status"] == "success"}
            if not successful.issubset(saved):
                return False
        return True

    def _refresh(self, envelope: _Envelope, *, persist_expired: bool = False) -> dict[str, dict]:
        now = utc_now()
        contents = {}
        missing = {}
        for name in ARTIFACT_NAMES:
            content, reason = self._inspect(envelope, name, now)
            if reason is None:
                contents[name] = content
            else:
                missing[name] = reason
        newly_expired = any(
            reason == "expired" and envelope.record.missing_artifacts.get(name) != "expired"
            for name, reason in missing.items()
        )
        envelope.record.missing_artifacts = missing
        envelope.record.recoverable = self._recoverable(envelope.record, contents)
        if persist_expired and newly_expired:
            self._persist(envelope)
        return contents

    @staticmethod
    def _error(envelope: _Envelope, error: LogAgentError) -> None:
        info = error.to_info()
        if info not in envelope.record.errors:
            envelope.record.errors.append(info)

    async def create(self, workflow_id: str, snapshot: WorkflowSnapshot, backup: BackupPolicy) -> SessionRecord:
        validate_id(workflow_id)
        if not isinstance(snapshot, WorkflowSnapshot) or not isinstance(backup, BackupPolicy):
            raise LogAgentError("VALIDATION_ERROR", "create requires a WorkflowSnapshot and BackupPolicy")
        snapshot, backup = deepcopy(snapshot), deepcopy(backup)
        async with self._index_lock:
            session_id = uuid4().hex
            return await self._operation(session_id, self._create, workflow_id, snapshot, backup)

    def _create(
        self, session_id: str, workflow_id: str, snapshot: WorkflowSnapshot, backup: BackupPolicy
    ) -> SessionRecord:
        try:
            backup = BackupPolicy.model_validate(backup.model_dump(mode="python"))
            content = _content("snapshot", snapshot.model_dump(mode="python"), session_id, workflow_id)
            snapshot_bytes = json_bytes(content)
        except ValidationError as exc:
            raise validation_error(exc) from exc
        except ValueError as exc:
            raise LogAgentError("VALIDATION_ERROR", "Snapshot content or Workflow association is invalid") from exc
        now = utc_now()
        _expires_at(now, backup)
        record = SessionRecord(id=session_id, workflow_id=workflow_id, created_at=now, updated_at=now)
        envelope = _Envelope(
            format_version=FORMAT_VERSION,
            backup=backup,
            record=record,
            snapshot_sha256=hashlib.sha256(snapshot_bytes).hexdigest(),
        )
        self._refresh(envelope)
        directory = self._path(session_id).parent
        directory.mkdir(parents=True, exist_ok=False)
        try:
            self._persist(envelope)
        except OSError:
            try:
                directory.rmdir()
            except OSError:
                pass
            raise
        try:
            self._save_artifact(session_id, "snapshot", content)
        except LogAgentError as exc:
            if exc.code != "ARTIFACT_WRITE_FAILED":
                raise
        return self._get(session_id)

    def _get(self, session_id: str) -> SessionRecord:
        envelope = self._read(session_id)
        self._refresh(envelope, persist_expired=True)
        return envelope.record

    async def get(self, session_id: str) -> SessionRecord:
        return await self._operation(session_id, self._get)

    def _session_ids(self) -> list[str]:
        try:
            paths = sorted(self.root.iterdir())
        except FileNotFoundError:
            return []
        result = []
        for path in paths:
            if path.is_symlink():
                raise LogAgentError("ARCHIVE_UNAVAILABLE", "Archive contains a symlink")
            if path.is_dir():
                validate_id(path.name)
                result.append(path.name)
        return result

    async def _ids(self) -> list[str]:
        async with self._index_lock:
            return await self._io(self._session_ids)

    async def list(self, workflow_id: str | None = None, limit: int | None = 100) -> list[SessionRecord]:
        if workflow_id is not None:
            validate_id(workflow_id)
        if limit is not None and (type(limit) is not int or limit < 1):
            raise LogAgentError("VALIDATION_ERROR", "limit must be a positive integer or null")
        records = []
        for session_id in await self._ids():
            record = await self.get(session_id)
            if workflow_id is None or record.workflow_id == workflow_id:
                records.append(record)
        records.sort(key=lambda record: (record.created_at, record.id), reverse=True)
        return records if limit is None else records[:limit]

    async def update(self, session_id: str, **changes) -> SessionRecord:
        return await self._operation(session_id, self._update, deepcopy(changes))

    def _update(self, session_id: str, changes: dict) -> SessionRecord:
        envelope = self._read(session_id)
        self._refresh(envelope, persist_expired=True)
        if STORE_FIELDS.intersection(changes):
            raise LogAgentError("CONFLICT", "Cannot modify Store-managed record fields", {"session_id": session_id})
        try:
            candidate = SessionRecord.model_validate({**envelope.record.model_dump(mode="python"), **changes})
        except ValidationError as exc:
            raise validation_error(exc) from exc
        if envelope.record.output_frozen and (
            not candidate.output_frozen
            or ("stage" in changes and candidate.stage in {"collect", "analyze", "aggregate"})
        ):
            raise LogAgentError("CONFLICT", "Frozen output cannot be reset", {"session_id": session_id})
        if (candidate.stage == "notify" or candidate.deliveries) and not candidate.output_frozen:
            raise LogAgentError("CONFLICT", "Output must be frozen before notification", {"session_id": session_id})
        receipts = {(delivery.output_id, delivery.channel_id): delivery for delivery in candidate.deliveries}
        if len(receipts) != len(candidate.deliveries):
            raise LogAgentError("VALIDATION_ERROR", "Delivery receipts must have unique output and channel pairs")
        for previous in envelope.record.deliveries:
            uncertain = previous.error is not None and previous.error.details.get("delivery_uncertain") is True
            if (previous.status == DeliveryStatus.SUCCESS or uncertain) and receipts.get(
                (previous.output_id, previous.channel_id)
            ) != previous:
                raise LogAgentError(
                    "CONFLICT",
                    "Settled or uncertain delivery receipts must be preserved",
                    {"session_id": session_id},
                )
        envelope.record = candidate
        self._refresh(envelope)
        self._persist(envelope)
        if candidate.status == SessionStatus.RUNNING:
            self._active_ids.add(session_id)
        else:
            self._active_ids.discard(session_id)
        return candidate

    async def save_artifact(self, session_id: str, name: str, content: Any) -> bool:
        self._name(name)
        return await self._operation(session_id, self._save_artifact, name, deepcopy(content))

    def _save_artifact(self, session_id: str, name: str, content: Any) -> bool:
        envelope = self._read(session_id)
        contents = self._refresh(envelope, persist_expired=True)
        if self._policy_reason(envelope, name):
            return False
        try:
            value = _content(name, content, session_id, envelope.record.workflow_id)
            raw = json_bytes(value)
        except ValidationError as exc:
            raise validation_error(exc, prefix=(name,)) from exc
        except ValueError as exc:
            raise LogAgentError(
                "VALIDATION_ERROR", "Artifact content is invalid", {"session_id": session_id, "name": name}
            ) from exc
        digest = hashlib.sha256(raw).hexdigest()
        if name == "snapshot" and digest != envelope.snapshot_sha256:
            raise LogAgentError("CONFLICT", "A session must retain its original snapshot", {"session_id": session_id})
        if envelope.record.output_frozen or (name == "snapshot" and name in envelope.record.artifacts):
            if name not in contents or json_bytes(contents[name]) != raw:
                raise LogAgentError(
                    "CONFLICT", "Immutable artifact cannot be replaced", {"session_id": session_id, "name": name}
                )
            return True
        if envelope.record.missing_artifacts.get(name) == "expired":
            raise self._unavailable(session_id, name, "expired")
        now = utc_now()
        info = ArtifactInfo(sha256=digest, size=len(raw), written_at=now, expires_at=_expires_at(now, envelope.backup))
        try:
            atomic_write(self._path(session_id, name + ".json"), raw)
        except OSError as exc:
            error = LogAgentError(
                "ARTIFACT_WRITE_FAILED",
                "Cannot save stage content",
                {"session_id": session_id, "name": name, "reason": "write_failed"},
            )
            envelope.record.missing_artifacts[name] = "write_failed"
            self._error(envelope, error)
            self._refresh(envelope)
            self._persist(envelope)
            raise error from exc
        envelope.record.artifacts[name] = info
        envelope.record.missing_artifacts.pop(name, None)
        self._refresh(envelope)
        self._persist(envelope)
        return True

    @staticmethod
    def _unavailable(session_id: str, name: str, reason: str) -> LogAgentError:
        return LogAgentError(
            "ARTIFACT_UNAVAILABLE",
            "Stage content is unavailable",
            {"session_id": session_id, "name": name, "reason": reason},
        )

    async def load_artifact(self, session_id: str, name: str) -> dict:
        self._name(name)
        return await self._operation(session_id, self._load_artifact, name)

    def _load_artifact(self, session_id: str, name: str) -> dict:
        envelope = self._read(session_id)
        content, reason = self._inspect(envelope, name, utc_now())
        if reason == "expired" and envelope.record.missing_artifacts.get(name) != "expired":
            envelope.record.missing_artifacts[name] = "expired"
            self._refresh(envelope)
            self._persist(envelope)
        if reason:
            raise self._unavailable(session_id, name, reason)
        return content

    async def availability(self, session_id: str) -> dict:
        record = await self.get(session_id)
        return {
            "available": [name for name in ARTIFACT_NAMES if name not in record.missing_artifacts],
            "missing_artifacts": record.missing_artifacts,
            "recoverable": record.recoverable,
        }

    async def mark_interrupted(self) -> list[SessionRecord]:
        """Call during startup, before accepting work; never resume any session."""
        interrupted = []
        for session_id in await self._ids():
            record = await self._operation(session_id, self._mark_interrupted)
            if record is not None:
                interrupted.append(record)
        return interrupted

    def _mark_interrupted(self, session_id: str) -> SessionRecord | None:
        envelope = self._read(session_id)
        if envelope.record.status != SessionStatus.RUNNING or session_id in self._active_ids:
            return None
        envelope.record.status = SessionStatus.INTERRUPTED
        self._error(
            envelope, LogAgentError("RUN_INTERRUPTED", "Previous run did not finish", {"session_id": session_id})
        )
        self._refresh(envelope)
        self._persist(envelope)
        return envelope.record

    async def expire(self) -> dict:
        summary = {"sessions": 0, "artifacts": 0, "errors": []}
        for session_id in await self._ids():
            result = await self._operation(session_id, self._expire)
            summary["sessions"] += result["sessions"]
            summary["artifacts"] += result["artifacts"]
            summary["errors"].extend(result["errors"])
        return summary

    def _expire(self, session_id: str) -> dict:
        summary = {"sessions": 0, "artifacts": 0, "errors": []}
        envelope = self._read(session_id)
        record = envelope.record
        if record.status in ACTIVE_STATUSES:
            return summary
        now = utc_now()
        expired = [
            name
            for name, info in record.artifacts.items()
            if (
                record.missing_artifacts.get(name) == "expired"
                or (info.expires_at is not None and now >= info.expires_at)
            )
            and (record.missing_artifacts.get(name) != "expired" or self._path(session_id, name + ".json").exists())
        ]
        if not expired:
            return summary
        for name in expired:
            record.missing_artifacts[name] = "expired"
        self._refresh(envelope)
        self._persist(envelope)
        summary["sessions"] = 1
        for name in expired:
            try:
                self._path(session_id, name + ".json").unlink()
                summary["artifacts"] += 1
            except FileNotFoundError:
                pass
            except OSError:
                error = LogAgentError(
                    "ARTIFACT_DELETE_FAILED",
                    "Cannot remove expired stage content",
                    {"session_id": session_id, "name": name, "reason": "expired"},
                )
                self._error(envelope, error)
                summary["errors"].append(error.as_dict())
        if summary["errors"]:
            self._persist(envelope)
        return summary
