"""Small transactional SQLite resource store used by the application services.

The store persists reusable configuration only.  Execution state and stage
artifacts deliberately do not belong here.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from logagent.errors import LogAgentError, validation_error
from logagent.models import (
    AIConfig,
    ChannelConfig,
    ResourceKind,
    SetterTemplate,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)

_MODELS: dict[str, type] = {
    "sources": SourceConfig,
    "setters": SetterTemplate,
    "ai": AIConfig,
    "channels": ChannelConfig,
    "workflows": WorkflowDefinition,
}


class SQLiteResourceStore:
    """Persist and snapshot reusable resources in a single SQLite database."""

    def __init__(self, location: str | Path = "data/resources.sqlite3") -> None:
        self.location = str(location)
        if self.location != ":memory:":
            Path(self.location).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.location, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS resources (kind TEXT NOT NULL, id TEXT NOT NULL, "
            "payload TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(kind,id))"
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> SQLiteResourceStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _kind(kind: str) -> str:
        if kind not in _MODELS:
            raise LogAgentError("invalid_argument", "资源类型无效", {"kind": kind})
        return kind

    def _validate(self, kind: str, resource: Any) -> tuple[str, str]:
        kind = self._kind(kind)
        model = _MODELS[kind]
        try:
            value = model.model_validate(resource)
        except ValidationError as exc:
            raise validation_error(exc, code="invalid_config") from None
        payload = value.model_dump(mode="json")
        return value.id, json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    def save(self, kind: ResourceKind | str, resource: Any, *, mode: str = "upsert") -> Any:
        if mode not in {"create", "replace", "upsert"}:
            raise LogAgentError("invalid_argument", "保存模式无效")
        kind = self._kind(kind)
        ident, payload = self._validate(kind, resource)
        with self._lock:
            exists = self._db.execute(
                "SELECT 1 FROM resources WHERE kind=? AND id=?", (kind, ident)
            ).fetchone() is not None
            if mode == "create" and exists:
                raise LogAgentError("already_exists", "资源已存在", {"kind": kind, "id": ident})
            if mode == "replace" and not exists:
                raise LogAgentError("not_found", "资源不存在", {"kind": kind, "id": ident})
            try:
                self._db.execute(
                    "INSERT INTO resources(kind,id,payload,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                    (kind, ident, payload, datetime.now(UTC).isoformat()),
                )
                self._db.commit()
            except sqlite3.Error as exc:
                self._db.rollback()
                raise LogAgentError("storage_failed", "资源保存失败", {"exception_type": type(exc).__name__}) from None
        return self.get(kind, ident)

    def get(self, kind: ResourceKind | str, ident: str) -> Any | None:
        kind = self._kind(kind)
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM resources WHERE kind=? AND id=?", (kind, ident)
            ).fetchone()
        if row is None:
            return None
        try:
            return _MODELS[kind].model_validate(json.loads(row[0]), strict=True)
        except (ValueError, ValidationError):
            raise LogAgentError("storage_corrupt", "资源存储内容无效", {"kind": kind}) from None

    def list(self, kind: ResourceKind | str) -> list[Any]:
        kind = self._kind(kind)
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM resources WHERE kind=? ORDER BY id", (kind,)
            ).fetchall()
        try:
            return [_MODELS[kind].model_validate(json.loads(row[0]), strict=True) for row in rows]
        except (ValueError, ValidationError):
            raise LogAgentError("storage_corrupt", "资源存储内容无效", {"kind": kind}) from None

    def delete(self, kind: ResourceKind | str, ident: str) -> None:
        kind = self._kind(kind)
        with self._lock:
            cursor = self._db.execute("DELETE FROM resources WHERE kind=? AND id=?", (kind, ident))
            self._db.commit()
        if cursor.rowcount == 0:
            raise LogAgentError("not_found", "资源不存在", {"kind": kind, "id": ident})

    def snapshot(self, workflow_id: str) -> WorkflowSnapshot:
        definition = self.get("workflows", workflow_id)
        if definition is None:
            raise LogAgentError("not_found", "Workflow 不存在", {"workflow_id": workflow_id})
        sources: dict[str, SourceConfig] = {}
        for ident in definition.sources:
            source = self.get("sources", ident)
            if source is None:
                raise LogAgentError("invalid_reference", "Workflow 引用的来源不存在", {"source": ident})
            sources[ident] = source
        ai_ids = {task.ai for task in definition.analyses}
        if definition.fan_in and definition.fan_in.ai:
            ai_ids.add(definition.fan_in.ai)
        ai: dict[str, AIConfig] = {}
        for ident in ai_ids:
            value = self.get("ai", ident)
            if value is None:
                raise LogAgentError("invalid_reference", "Workflow 引用的 AI 不存在", {"ai": ident})
            ai[ident] = value
        channels: dict[str, ChannelConfig] = {}
        for ident in definition.channels:
            value = self.get("channels", ident)
            if value is None:
                raise LogAgentError("invalid_reference", "Workflow 引用的 Channel 不存在", {"channel": ident})
            channels[ident] = value
        return WorkflowSnapshot(
            workflow=deepcopy(definition), sources=sources, ai=ai, channels=channels,
            created_at=datetime.now(UTC),
        )


ResourceStore = SQLiteResourceStore

