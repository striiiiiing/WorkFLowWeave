"""Durable workflow facts and user-visible history in SQLite.

LangGraph owns its checkpoint tables in the same database. This store retains
the immutable configuration snapshot and completed work across graph retries.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from logagent.errors import LogAgentError
from logagent.models import ID, DeliveryResult, ErrorInfo, JSONObject, WorkflowSnapshot

_JSON = TypeAdapter(JSONObject)
_ID = TypeAdapter(ID)
_CLAIMS: dict[tuple[str, str], object] = {}
_CLAIM_LOCK = threading.Lock()


def _encode(value: Any) -> tuple[str, str]:
    try:
        value = _JSON.validate_python(value, strict=True)
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()
    except (ValidationError, ValueError, TypeError, RecursionError, UnicodeError):
        raise LogAgentError("invalid_argument", "Workflow 存储需要有效 JSON 对象") from None


def _decode(payload: str, digest: str) -> dict[str, Any]:
    try:
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
            raise ValueError("Checksum mismatch")
        return _JSON.validate_python(json.loads(payload), strict=True)
    except (ValidationError, ValueError, TypeError, AttributeError, RecursionError, UnicodeError):
        raise LogAgentError("storage_corrupt", "Workflow 存储内容无效") from None


def _ident(value: str) -> None:
    try:
        _ID.validate_python(value, strict=True)
    except ValidationError:
        raise LogAgentError("invalid_argument", "Workflow 标识无效") from None


def _label(value: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise LogAgentError("invalid_argument", "Workflow 阶段或状态无效")


def _page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
        raise LogAgentError("invalid_argument", "分页参数无效")


class SQLiteRunStore:
    """Transactional stage history, item results, and notification send intents.

    Claims prevent concurrent execution through store instances in one process.
    Run one workflow executor process per database; SQLite itself also serializes
    each individual write transaction. Checksums and journal verification detect
    accidental corruption, not an adversary editing both facts and their journal.
    """

    def __init__(
        self, location: str | Path = "data/workflows.sqlite3", *, read_only: bool = False
    ) -> None:
        self.location = str(location)
        if not self.location or "\x00" in self.location:
            raise LogAgentError("invalid_argument", "Workflow 数据库路径无效")
        if read_only and self.location == ":memory:":
            raise LogAgentError("invalid_argument", "只读查询需要既有 SQLite 数据库文件")
        self.read_only = read_only
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None
        self._owner = object()
        try:
            self._claim_location = (
                f":memory:{id(self)}"
                if self.location == ":memory:"
                else str(Path(self.location).resolve())
            )
            if read_only:
                uri = Path(self._claim_location).as_uri() + "?mode=ro"
                self._db = sqlite3.connect(uri, uri=True, timeout=30, check_same_thread=False)
            else:
                if self.location != ":memory:":
                    Path(self.location).parent.mkdir(parents=True, exist_ok=True)
                self._db = sqlite3.connect(self.location, timeout=30, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA busy_timeout=30000")
            if read_only:
                self._db.execute("PRAGMA query_only=ON")
                version = self._db.execute("SELECT version FROM run_schema WHERE id=1").fetchone()
                if version is None or version[0] != 1:
                    raise LogAgentError("storage_version", "Workflow 数据库版本不受支持")
            else:
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.execute("PRAGMA synchronous=FULL")
                self._initialize()
        except (OSError, sqlite3.Error):
            self.close()
            raise LogAgentError("storage_failed", "Workflow 数据库初始化失败") from None
        except LogAgentError:
            self.close()
            raise

    @contextmanager
    def _connection(
        self, *, write: bool = False, read_transaction: bool = False
    ) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._db is None:
                raise LogAgentError("storage_closed", "Workflow 数据库已关闭")
            if write and self.read_only:
                raise LogAgentError("storage_readonly", "Workflow 数据库为只读模式")
            transaction = write or read_transaction
            try:
                if transaction:
                    self._db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield self._db
                if transaction:
                    self._db.commit()
            except sqlite3.Error as exc:
                if transaction:
                    try:
                        self._db.rollback()
                    except sqlite3.Error:
                        pass
                raise LogAgentError(
                    "storage_failed",
                    "Workflow 数据库操作失败",
                    {"exception_type": type(exc).__name__},
                ) from None
            except BaseException:
                if transaction:
                    try:
                        self._db.rollback()
                    except sqlite3.Error:
                        pass
                raise

    def _initialize(self) -> None:
        with self._connection(write=True) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS run_schema (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)"
            )
            version = db.execute("SELECT version FROM run_schema WHERE id=1").fetchone()
            if version is not None and version[0] != 1:
                raise LogAgentError("storage_version", "Workflow 数据库版本不受支持")
            db.execute("INSERT OR IGNORE INTO run_schema(id,version) VALUES(1,1)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS run_sessions ("
                "session_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, status TEXT NOT NULL, "
                "stage TEXT NOT NULL, snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL, "
                "context_json TEXT NOT NULL, context_hash TEXT NOT NULL, "
                "error_json TEXT NOT NULL, error_hash TEXT NOT NULL, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS run_stages ("
                "session_id TEXT NOT NULL REFERENCES run_sessions(session_id), stage TEXT NOT NULL, "
                "status TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, "
                "PRIMARY KEY(session_id,stage))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS run_items ("
                "session_id TEXT NOT NULL REFERENCES run_sessions(session_id), stage TEXT NOT NULL, "
                "item_key TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL, "
                "payload_hash TEXT NOT NULL, PRIMARY KEY(session_id,stage,item_key))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS run_history ("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                "session_id TEXT NOT NULL REFERENCES run_sessions(session_id), stage TEXT NOT NULL, "
                "event TEXT NOT NULL, item_key TEXT, payload_json TEXT NOT NULL, "
                "payload_hash TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS run_history_session ON run_history(session_id,seq)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS run_sessions_workflow ON run_sessions(workflow_id,created_at)"
            )

    @staticmethod
    def _require_session(db: sqlite3.Connection, session_id: str) -> sqlite3.Row:
        _ident(session_id)
        row = db.execute("SELECT * FROM run_sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise LogAgentError("not_found", "Workflow session 不存在", {"session_id": session_id})
        return row

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        session_id: str,
        stage: str,
        event: str,
        payload: str,
        digest: str,
        item_key: str | None = None,
    ) -> None:
        db.execute(
            "INSERT INTO run_history(session_id,stage,event,item_key,payload_json,payload_hash,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (session_id, stage, event, item_key, payload, digest, datetime.now(UTC).isoformat()),
        )

    def create_session(
        self,
        session_id: str,
        snapshot: WorkflowSnapshot | dict[str, Any],
        context_data: dict[str, Any],
    ) -> None:
        _ident(session_id)
        try:
            raw = (
                snapshot.model_dump(mode="json")
                if isinstance(snapshot, WorkflowSnapshot)
                else snapshot
            )
            validated = WorkflowSnapshot.model_validate(raw, strict=True)
        except (ValidationError, ValueError, TypeError):
            raise LogAgentError("invalid_argument", "Workflow snapshot 无效") from None
        snapshot_json, snapshot_hash = _encode(validated.model_dump(mode="json"))
        context_json, context_hash = _encode(context_data)
        empty, empty_hash = _encode({})
        now = datetime.now(UTC).isoformat()
        with self._connection(write=True) as db:
            if db.execute(
                "SELECT 1 FROM run_sessions WHERE session_id=?", (session_id,)
            ).fetchone():
                raise LogAgentError(
                    "session_exists", "Workflow session 已存在", {"session_id": session_id}
                )
            db.execute(
                "INSERT INTO run_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    validated.workflow.id,
                    "running",
                    "created",
                    snapshot_json,
                    snapshot_hash,
                    context_json,
                    context_hash,
                    empty,
                    empty_hash,
                    now,
                    now,
                ),
            )
            self._event(db, session_id, "created", "created", context_json, context_hash)

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._connection() as db:
            row = self._require_session(db, session_id)
        snapshot = _decode(row["snapshot_json"], row["snapshot_hash"])
        try:
            WorkflowSnapshot.model_validate(snapshot, strict=True)
        except ValidationError:
            raise LogAgentError("storage_corrupt", "Workflow snapshot 存储内容无效") from None
        return {
            "session_id": row["session_id"],
            "workflow_id": row["workflow_id"],
            "status": row["status"],
            "stage": row["stage"],
            "snapshot": snapshot,
            "context": _decode(row["context_json"], row["context_hash"]),
            "error": _decode(row["error_json"], row["error_hash"]).get("error"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def verify_session(self, session_id: str) -> None:
        """Validate durable facts against their journal before any resumed I/O.

        A single SQLite read transaction prevents comparing rows committed at
        different times. Missing terminal facts and their corresponding journal
        entries are corruption, not permission to repeat completed operations.
        """
        with self._connection(read_transaction=True) as db:
            session = self._require_session(db, session_id)
            snapshot = _decode(session["snapshot_json"], session["snapshot_hash"])
            context = _decode(session["context_json"], session["context_hash"])
            error = _decode(session["error_json"], session["error_hash"])
            try:
                validated = WorkflowSnapshot.model_validate(snapshot, strict=True)
                if validated.workflow.id != session["workflow_id"]:
                    raise ValueError("Snapshot identity mismatch")
                if error.get("error") is not None:
                    ErrorInfo.model_validate(error["error"], strict=True)
            except (ValidationError, ValueError, TypeError):
                raise LogAgentError("storage_corrupt", "Workflow session 存储内容无效") from None
            stages = db.execute(
                "SELECT * FROM run_stages WHERE session_id=?", (session_id,)
            ).fetchall()
            items = db.execute(
                "SELECT * FROM run_items WHERE session_id=?", (session_id,)
            ).fetchall()
            events = db.execute(
                "SELECT * FROM run_history WHERE session_id=? ORDER BY seq", (session_id,)
            ).fetchall()
            for row in [*stages, *items]:
                _decode(row["payload_json"], row["payload_hash"])
            values = [(_decode(row["payload_json"], row["payload_hash"]), row) for row in events]
            self._verify_facts(session_id, context, stages, items, values)

    @staticmethod
    def _verify_facts(
        session_id: str,
        context: dict[str, Any],
        stages: list[sqlite3.Row],
        items: list[sqlite3.Row],
        events: list[tuple[dict[str, Any], sqlite3.Row]],
    ) -> None:
        def corrupt() -> None:
            raise LogAgentError("storage_corrupt", "Workflow 已提交结果与阶段历史不一致")

        if not events:
            corrupt()
        first_payload, first = events[0]
        if (
            first["event"] != "created"
            or first["stage"] != "created"
            or first["item_key"] is not None
            or first_payload != context
        ):
            corrupt()
        latest_items: dict[tuple[str, str], sqlite3.Row] = {}
        completed_stages: dict[str, sqlite3.Row] = {}
        stage_events: set[tuple[str, str, str, str]] = set()
        for payload, event in events:
            if event["item_key"] is not None:
                latest_items[(event["stage"], event["item_key"])] = event
            else:
                stage_events.add(
                    (event["stage"], event["event"], event["payload_json"], event["payload_hash"])
                )
                if event["event"] == "completed" and "session_id" in payload and "stage" in payload:
                    if payload["session_id"] != session_id or payload["stage"] != event["stage"]:
                        corrupt()
                    completed_stages[event["stage"]] = event
        stored_items = {(row["stage"], row["item_key"]): row for row in items}
        if stored_items.keys() != latest_items.keys():
            corrupt()
        for key, row in stored_items.items():
            event = latest_items[key]
            if (
                row["status"] != event["event"]
                or row["payload_json"] != event["payload_json"]
                or row["payload_hash"] != event["payload_hash"]
            ):
                corrupt()
        stored_stages = {row["stage"]: row for row in stages}
        for stage, event in completed_stages.items():
            row = stored_stages.get(stage)
            if (
                row is None
                or row["status"] != "completed"
                or row["payload_json"] != event["payload_json"]
                or row["payload_hash"] != event["payload_hash"]
            ):
                corrupt()
        for row in stages:
            if (
                row["stage"],
                row["status"],
                row["payload_json"],
                row["payload_hash"],
            ) not in stage_events:
                corrupt()

    def set_status(self, session_id: str, status: str, error: ErrorInfo | None = None) -> None:
        _label(status)
        if error is not None and not isinstance(error, ErrorInfo):
            raise LogAgentError("invalid_argument", "Workflow error 无效")
        payload, digest = _encode({"error": error.model_dump(mode="json") if error else None})
        with self._connection(write=True) as db:
            row = self._require_session(db, session_id)
            db.execute(
                "UPDATE run_sessions SET status=?,error_json=?,error_hash=?,updated_at=? WHERE session_id=?",
                (status, payload, digest, datetime.now(UTC).isoformat(), session_id),
            )
            self._event(db, session_id, row["stage"], status, payload, digest)

    def list_sessions(
        self, workflow_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        _page(limit, offset)
        if workflow_id is not None:
            _ident(workflow_id)
        query = "SELECT session_id,workflow_id,status,stage,created_at,updated_at FROM run_sessions"
        params: tuple = ()
        if workflow_id is not None:
            query += " WHERE workflow_id=?"
            params = (workflow_id,)
        with self._connection() as db:
            rows = db.execute(
                query + " ORDER BY created_at DESC,session_id LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def history(
        self, session_id: str, stage: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        _page(limit, offset)
        query = "SELECT * FROM run_history WHERE session_id=?"
        params: tuple = (session_id,)
        if stage is not None:
            _label(stage)
            query += " AND stage=?"
            params += (stage,)
        with self._connection() as db:
            self._require_session(db, session_id)
            rows = db.execute(
                query + " ORDER BY seq LIMIT ? OFFSET ?", (*params, limit, offset)
            ).fetchall()
        return [
            {
                "seq": row["seq"],
                "stage": row["stage"],
                "event": row["event"],
                "item_key": row["item_key"],
                "payload": _decode(row["payload_json"], row["payload_hash"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def append_history(
        self, session_id: str, stage: str, event: str, payload: dict[str, Any]
    ) -> None:
        """Record stage progress and advance the session's displayed stage atomically."""
        _label(stage)
        _label(event)
        encoded, digest = _encode(payload)
        with self._connection(write=True) as db:
            self._require_session(db, session_id)
            db.execute(
                "UPDATE run_sessions SET stage=?,updated_at=? WHERE session_id=?",
                (stage, datetime.now(UTC).isoformat(), session_id),
            )
            self._event(db, session_id, stage, event, encoded, digest)

    def stage_result(self, session_id: str, stage: str) -> dict[str, Any] | None:
        _label(stage)
        with self._connection() as db:
            self._require_session(db, session_id)
            row = db.execute(
                "SELECT * FROM run_stages WHERE session_id=? AND stage=?", (session_id, stage)
            ).fetchone()
        if row is None:
            return None
        payload = _decode(row["payload_json"], row["payload_hash"])
        return payload if row["status"] == "completed" else None

    def save_stage(
        self, session_id: str, stage: str, payload: dict[str, Any], status: str = "completed"
    ) -> None:
        _label(stage)
        _label(status)
        encoded, digest = _encode(payload)
        with self._connection(write=True) as db:
            self._require_session(db, session_id)
            previous = db.execute(
                "SELECT * FROM run_stages WHERE session_id=? AND stage=?", (session_id, stage)
            ).fetchone()
            if previous is not None:
                _decode(previous["payload_json"], previous["payload_hash"])
                if previous["status"] == "completed":
                    if status == "completed" and previous["payload_json"] == encoded:
                        return
                    raise LogAgentError("storage_conflict", "已完成的 Workflow 阶段不可更改")
            db.execute(
                "INSERT INTO run_stages VALUES(?,?,?,?,?) ON CONFLICT(session_id,stage) DO UPDATE SET "
                "status=excluded.status,payload_json=excluded.payload_json,payload_hash=excluded.payload_hash",
                (session_id, stage, status, encoded, digest),
            )
            db.execute(
                "UPDATE run_sessions SET stage=?,updated_at=? WHERE session_id=?",
                (stage, datetime.now(UTC).isoformat(), session_id),
            )
            self._event(db, session_id, stage, status, encoded, digest)

    def item_results(self, session_id: str, stage: str) -> dict[str, dict[str, Any]]:
        _label(stage)
        with self._connection() as db:
            self._require_session(db, session_id)
            rows = db.execute(
                "SELECT * FROM run_items WHERE session_id=? AND stage=? ORDER BY item_key",
                (session_id, stage),
            ).fetchall()
        return {row["item_key"]: _decode(row["payload_json"], row["payload_hash"]) for row in rows}

    def save_item(self, session_id: str, stage: str, key: str, payload: dict[str, Any]) -> None:
        _label(stage)
        _label(key)
        encoded, digest = _encode(payload)
        status = payload.get("status", "completed")
        _label(status)
        with self._connection(write=True) as db:
            self._require_session(db, session_id)
            previous = db.execute(
                "SELECT * FROM run_items WHERE session_id=? AND stage=? AND item_key=?",
                (session_id, stage, key),
            ).fetchone()
            if previous is not None:
                _decode(previous["payload_json"], previous["payload_hash"])
                if previous["status"] in {
                    "success",
                    "completed",
                    "empty",
                    "filtered_empty",
                    "skipped",
                }:
                    if previous["payload_json"] == encoded:
                        return
                    raise LogAgentError("storage_conflict", "已完成的 Workflow 结果不可更改")
                if previous["status"] == "sending":
                    raise LogAgentError("storage_conflict", "发送意图必须由通知回执完成")
            db.execute(
                "INSERT INTO run_items VALUES(?,?,?,?,?,?) ON CONFLICT(session_id,stage,item_key) DO UPDATE SET "
                "status=excluded.status,payload_json=excluded.payload_json,payload_hash=excluded.payload_hash",
                (session_id, stage, key, status, encoded, digest),
            )
            self._event(db, session_id, stage, status, encoded, digest, key)

    @staticmethod
    def _delivery_key(output_id: str, channel_id: str) -> str:
        _ident(output_id)
        _ident(channel_id)
        return f"{output_id}:{channel_id}"

    def begin_delivery(self, session_id: str, output_id: str, channel_id: str) -> bool:
        key = self._delivery_key(output_id, channel_id)
        encoded, digest = _encode(
            {"output_id": output_id, "channel_id": channel_id, "status": "sending"}
        )
        with self._connection(write=True) as db:
            self._require_session(db, session_id)
            previous = db.execute(
                "SELECT * FROM run_items WHERE session_id=? AND stage='notify' AND item_key=?",
                (session_id, key),
            ).fetchone()
            if previous is not None:
                _decode(previous["payload_json"], previous["payload_hash"])
                return False
            db.execute(
                "INSERT INTO run_items VALUES(?,'notify',?,'sending',?,?)",
                (session_id, key, encoded, digest),
            )
            self._event(db, session_id, "notify", "sending", encoded, digest, key)
        return True

    def delivery_results(self, session_id: str) -> list[dict[str, Any]]:
        results = []
        for payload in self.item_results(session_id, "notify").values():
            if payload.get("status") == "sending":
                payload = {
                    "channel_id": payload.get("channel_id"),
                    "output_id": payload.get("output_id"),
                    "status": "failed",
                    "attempts": 1,
                    "error": {
                        "code": "delivery_uncertain",
                        "message": "通知已开始发送但没有持久化回执；为避免重复发送，不会自动重发",
                        "details": {"delivery_uncertain": True},
                    },
                }
            try:
                results.append(
                    DeliveryResult.model_validate(payload, strict=True).model_dump(mode="json")
                )
            except ValidationError:
                raise LogAgentError("storage_corrupt", "Workflow 通知回执存储内容无效") from None
        return results

    def save_delivery(self, session_id: str, result: DeliveryResult | dict[str, Any]) -> None:
        try:
            raw = result.model_dump(mode="json") if isinstance(result, DeliveryResult) else result
            validated = DeliveryResult.model_validate(raw, strict=True)
        except (ValidationError, ValueError, TypeError):
            raise LogAgentError("invalid_argument", "Workflow 通知回执无效") from None
        payload = validated.model_dump(mode="json")
        key = self._delivery_key(validated.output_id, validated.channel_id)
        encoded, digest = _encode(payload)
        with self._connection(write=True) as db:
            self._require_session(db, session_id)
            previous = db.execute(
                "SELECT * FROM run_items WHERE session_id=? AND stage='notify' AND item_key=?",
                (session_id, key),
            ).fetchone()
            if previous is None:
                raise LogAgentError("storage_conflict", "通知回执缺少发送意图")
            _decode(previous["payload_json"], previous["payload_hash"])
            if previous["status"] != "sending":
                if previous["payload_json"] == encoded:
                    return
                raise LogAgentError("storage_conflict", "已保存的通知回执不可更改")
            db.execute(
                "UPDATE run_items SET status=?,payload_json=?,payload_hash=? "
                "WHERE session_id=? AND stage='notify' AND item_key=?",
                (validated.status, encoded, digest, session_id, key),
            )
            self._event(db, session_id, "notify", validated.status, encoded, digest, key)

    def claim(self, session_id: str) -> bool:
        _ident(session_id)
        with self._lock, _CLAIM_LOCK:
            if self._db is None:
                raise LogAgentError("storage_closed", "Workflow 数据库已关闭")
            key = (self._claim_location, session_id)
            if key in _CLAIMS:
                return False
            _CLAIMS[key] = self._owner
            return True

    def release(self, session_id: str) -> None:
        with _CLAIM_LOCK:
            key = (self._claim_location, session_id)
            if _CLAIMS.get(key) is self._owner:
                del _CLAIMS[key]

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
            with _CLAIM_LOCK:
                for key in [key for key, owner in _CLAIMS.items() if owner is self._owner]:
                    del _CLAIMS[key]

    def __enter__(self) -> SQLiteRunStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
