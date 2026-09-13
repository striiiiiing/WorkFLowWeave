"""Bounded, read-only access to the v1 session archive format.

``data_dir/sessions/<id>/record.json`` stores SessionArchiveEnvelope. The other
fixed JSON files store raw artifact objects. Their indices and snapshot hash
refer to the exact UTF-8 file bytes, without another artifact envelope.

All filesystem work runs in worker threads. Directory descriptors anchor each
read, and child directories/files cannot redirect reads through symlinks.
Nothing here creates directories, repairs records, or starts workflow work.
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from logagent.errors import LogAgentError
from logagent.models import (
    ARTIFACT_MODELS,
    ARTIFACT_NAMES,
    ID,
    AnalysisArtifact,
    ArtifactAvailability,
    ArtifactContent,
    ArtifactName,
    CollectionArtifact,
    FinalArtifact,
    MissingReason,
    SessionArchiveEnvelope,
    SessionRecord,
    WorkflowSnapshot,
)

_ID = TypeAdapter(ID)
_ARTIFACT_NAME = TypeAdapter(ArtifactName)
_RESUMABLE_STATUSES = frozenset({"failed", "partial", "cancelled", "interrupted"})
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
_CHILD_DIRECTORY_FLAGS = _DIRECTORY_FLAGS | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def _parse_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant
    )


def _validate_id(value: str, field: str = "session_id") -> str:
    try:
        return _ID.validate_python(value)
    except ValidationError:
        raise LogAgentError("invalid_argument", "标识格式无效", {"field": field}) from None


def _artifact_error(
    session_id: str, name: ArtifactName, reason: MissingReason, cause: str | None = None
) -> LogAgentError:
    details: dict[str, Any] = {"session_id": session_id, "artifact": name, "reason": reason}
    if cause is not None:
        details["cause"] = cause
    return LogAgentError("artifact_unavailable", "阶段正文不可用", details)


class _UnsafeFile(ValueError):
    pass


def _read_bytes(directory_fd: int, filename: str, limit: int) -> bytes:
    """Open a regular child file and never request more than limit + 1 bytes."""
    file_fd = os.open(filename, _FILE_FLAGS, dir_fd=directory_fd)
    try:
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise _UnsafeFile("not_regular")
        if before.st_size > limit:
            raise _UnsafeFile("size_limit")
        with os.fdopen(file_fd, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(file_fd)
        if len(raw) > limit:
            raise _UnsafeFile("size_limit")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise _UnsafeFile("changed_during_read")
        return raw
    finally:
        os.close(file_fd)


class FileArchiveReader:
    """Read an existing archive beneath ``data_dir``, without any write API.

    Record files default to a 1 MiB limit and artifacts to 16 MiB. Larger files
    are reported as corrupt/unavailable, not partially parsed. ``clock`` is an
    injectable timezone-aware clock for expiration checks.
    """

    def __init__(
        self,
        data_dir: str | Path,
        *,
        max_record_bytes: int = 1024 * 1024,
        max_artifact_bytes: int = 16 * 1024 * 1024,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        for name, value in (
            ("max_record_bytes", max_record_bytes),
            ("max_artifact_bytes", max_artifact_bytes),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.sessions_dir = Path(data_dir).absolute() / "sessions"
        self._max_record_bytes = max_record_bytes
        self._max_artifact_bytes = max_artifact_bytes
        self._clock = clock

    async def get(self, session_id: str) -> SessionRecord:
        session_id = _validate_id(session_id)
        return await asyncio.to_thread(self._get, session_id)

    async def list(
        self, workflow_id: str | None = None, limit: int | None = 100
    ) -> list[SessionRecord]:
        if workflow_id is not None:
            workflow_id = _validate_id(workflow_id, "workflow_id")
        if limit is not None and (type(limit) is not int or limit < 1):
            raise LogAgentError("invalid_argument", "limit 必须为正整数或 None", {"field": "limit"})
        return await asyncio.to_thread(self._list, workflow_id, limit)

    async def load_artifact(self, session_id: str, name: ArtifactName) -> ArtifactContent:
        session_id = _validate_id(session_id)
        try:
            name = _ARTIFACT_NAME.validate_python(name)
        except ValidationError:
            raise LogAgentError("invalid_argument", "阶段名称无效", {"field": "artifact"}) from None
        return await asyncio.to_thread(self._load_artifact, session_id, name)

    async def availability(self, session_id: str) -> ArtifactAvailability:
        session_id = _validate_id(session_id)
        return await asyncio.to_thread(self._availability, session_id)

    @contextmanager
    def _root(self) -> Iterator[int]:
        root_fd = os.open(self.sessions_dir, _DIRECTORY_FLAGS)
        try:
            yield root_fd
        finally:
            os.close(root_fd)

    @contextmanager
    def _session(self, root_fd: int, session_id: str) -> Iterator[int]:
        session_fd = os.open(session_id, _CHILD_DIRECTORY_FLAGS, dir_fd=root_fd)
        try:
            yield session_fd
        finally:
            os.close(session_fd)

    @staticmethod
    def _record_os_error(exc: OSError, session_id: str | None = None) -> LogAgentError:
        details: dict[str, Any] = {"exception_type": type(exc).__name__}
        if session_id is not None:
            details["session_id"] = session_id
        if isinstance(exc, FileNotFoundError):
            return LogAgentError("session_not_found", "运行记录不存在", details)
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            return LogAgentError("archive_corrupt", "存档路径不是合法的文件或目录", details)
        return LogAgentError("archive_unavailable", "无法读取运行存档", details)

    def _envelope(self, session_fd: int, session_id: str) -> SessionArchiveEnvelope:
        try:
            raw = _read_bytes(session_fd, "record.json", self._max_record_bytes)
            value = _parse_json(raw)
            if not isinstance(value, dict) or "format_version" not in value:
                raise ValueError("Missing archive format version")
            envelope = SessionArchiveEnvelope.model_validate(value)
            if envelope.record.id != session_id:
                raise ValueError("Session ID does not match its directory")
            return envelope
        except (ValueError, UnicodeError, RecursionError):
            raise LogAgentError(
                "archive_corrupt", "运行记录格式或内容损坏", {"session_id": session_id}
            ) from None

    def _get(self, session_id: str) -> SessionRecord:
        try:
            with self._root() as root_fd, self._session(root_fd, session_id) as session_fd:
                return self._envelope(session_fd, session_id).record
        except OSError as exc:
            raise self._record_os_error(exc, session_id) from None

    def _list(self, workflow_id: str | None, limit: int | None) -> list[SessionRecord]:
        records: list[SessionRecord] = []
        session_id: str | None = None
        root_opened = False
        try:
            with self._root() as root_fd:
                root_opened = True
                with os.scandir(root_fd) as entries:
                    for entry in entries:
                        try:
                            session_id = _ID.validate_python(entry.name)
                        except ValidationError:
                            continue
                        if entry.is_symlink():
                            raise LogAgentError(
                                "archive_corrupt",
                                "运行目录不能是符号链接",
                                {"session_id": session_id},
                            )
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        with self._session(root_fd, session_id) as session_fd:
                            record = self._envelope(session_fd, session_id).record
                        if workflow_id is None or record.workflow_id == workflow_id:
                            records.append(record)
        except FileNotFoundError as exc:
            # Only absence at the initial root open means no saved sessions.
            # Once traversal starts, disappearing records are read failures,
            # even if the entire root has also disappeared in the meantime.
            if root_opened:
                raise self._record_os_error(exc, session_id) from None
            if self.sessions_dir.is_symlink():
                raise LogAgentError("archive_corrupt", "存档根目录符号链接不可用") from None
            return []
        except OSError as exc:
            raise self._record_os_error(exc, session_id) from None
        records.sort(key=lambda record: (record.created_at, record.id), reverse=True)
        return records if limit is None else records[:limit]

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Archive clock must return a timezone-aware datetime")
        return now.astimezone(UTC)

    def _artifact(
        self,
        session_fd: int,
        envelope: SessionArchiveEnvelope,
        name: ArtifactName,
        now: datetime,
    ) -> ArtifactContent:
        record = envelope.record
        session_id = record.id
        if not envelope.backup.enabled:
            raise _artifact_error(session_id, name, "disabled")
        if name not in envelope.backup.stages:
            raise _artifact_error(session_id, name, "out_of_scope")
        if reason := record.missing_artifacts.get(name):
            raise _artifact_error(session_id, name, reason)
        info = record.artifacts.get(name)
        if info is None:
            raise _artifact_error(session_id, name, "not_created")
        if info.expires_at is not None and now >= info.expires_at:
            raise _artifact_error(session_id, name, "expired")
        retention = envelope.backup.retention_days
        if retention is not None and (now - info.written_at).total_seconds() / 86400 >= retention:
            raise _artifact_error(session_id, name, "expired")
        if info.size > self._max_artifact_bytes:
            raise _artifact_error(session_id, name, "corrupt", "size_limit")
        try:
            raw = _read_bytes(session_fd, f"{name}.json", self._max_artifact_bytes)
        except FileNotFoundError:
            raise _artifact_error(session_id, name, "missing") from None
        except _UnsafeFile as exc:
            raise _artifact_error(session_id, name, "corrupt", str(exc)) from None
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise _artifact_error(session_id, name, "corrupt", "unsafe_path") from None
            raise LogAgentError(
                "archive_unavailable",
                "无法读取阶段正文",
                {
                    "session_id": session_id,
                    "artifact": name,
                    "exception_type": type(exc).__name__,
                },
            ) from None
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != info.size or digest != info.sha256:
            raise _artifact_error(session_id, name, "corrupt", "integrity_mismatch")
        if name == "snapshot" and digest != envelope.snapshot_sha256:
            raise _artifact_error(session_id, name, "corrupt", "snapshot_mismatch")
        try:
            artifact = ARTIFACT_MODELS[name].model_validate(_parse_json(raw))
            if (
                isinstance(artifact, WorkflowSnapshot)
                and artifact.workflow.id != record.workflow_id
            ):
                raise ValueError("Snapshot belongs to another workflow")
            if isinstance(artifact, FinalArtifact) and any(
                output.session_id != session_id for output in artifact.outputs
            ):
                raise ValueError("Output belongs to another session")
        except (ValueError, UnicodeError, RecursionError):
            raise _artifact_error(session_id, name, "corrupt", "invalid_content") from None
        return artifact

    def _load_artifact(self, session_id: str, name: ArtifactName) -> ArtifactContent:
        try:
            with self._root() as root_fd, self._session(root_fd, session_id) as session_fd:
                envelope = self._envelope(session_fd, session_id)
                return self._artifact(session_fd, envelope, name, self._now())
        except OSError as exc:
            raise self._record_os_error(exc, session_id) from None

    def _availability(self, session_id: str) -> ArtifactAvailability:
        available: dict[ArtifactName, ArtifactContent] = {}
        missing: dict[ArtifactName, MissingReason] = {}
        try:
            with self._root() as root_fd, self._session(root_fd, session_id) as session_fd:
                envelope = self._envelope(session_fd, session_id)
                now = self._now()
                for name in ARTIFACT_NAMES:
                    try:
                        available[name] = self._artifact(session_fd, envelope, name, now)
                    except LogAgentError as exc:
                        if exc.code != "artifact_unavailable":
                            raise
                        missing[name] = exc.details["reason"]
        except OSError as exc:
            raise self._record_os_error(exc, session_id) from None
        return ArtifactAvailability(
            available=list(available),
            missing_artifacts=missing,
            recoverable=self._recoverable(envelope.record, available),
        )

    @staticmethod
    def _recoverable(record: SessionRecord, artifacts: dict[ArtifactName, ArtifactContent]) -> bool:
        """A material hint; Workflow still decides which work is safe to resume."""
        snapshot = artifacts.get("snapshot")
        if record.status not in _RESUMABLE_STATUSES or not isinstance(snapshot, WorkflowSnapshot):
            return False
        task_ids = [task.id for task in snapshot.workflow.analyses]
        if record.output_frozen:
            final = artifacts.get("final")
            if not isinstance(final, FinalArtifact) or not final.outputs:
                return False
            allowed = {"final"} if snapshot.workflow.fan_in is not None else set(task_ids)
            if any(
                output.output_id not in allowed or not output.text.strip()
                for output in final.outputs
            ):
                return False
            receipts = {(item.output_id, item.channel_id): item for item in record.deliveries}
            for output in final.outputs:
                for channel_id in snapshot.workflow.channels:
                    if not snapshot.channels[channel_id].enabled:
                        continue
                    receipt = receipts.get((output.output_id, channel_id))
                    if receipt is None:
                        return True
                    uncertain = (
                        receipt.error is not None
                        and receipt.error.details.get("delivery_uncertain") is True
                    )
                    if receipt.status in ("failed", "timeout") and not uncertain:
                        return True
            return False
        collection = artifacts.get("collection")
        if not isinstance(collection, CollectionArtifact) or not collection.shared_input.strip():
            return False
        successes = {
            task_id for task_id, status in record.analysis_statuses.items() if status == "success"
        }
        if not set(record.analysis_statuses) <= set(task_ids):
            return False
        analysis = artifacts.get("analysis")
        if isinstance(analysis, AnalysisArtifact):
            if analysis.order != task_ids:
                return False
            saved_successes = {
                result.task_id for result in analysis.results if result.status == "success"
            }
            return successes <= saved_successes
        return not successes
