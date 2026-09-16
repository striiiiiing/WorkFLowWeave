"""Idempotent business archives; execution checkpoints belong to LangGraph."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import orjson
from pydantic import TypeAdapter

from logagent.errors import LogAgentError
from logagent.models import ID, BackupPolicy, JSONObject

_JSON = TypeAdapter(JSONObject)
_ID = TypeAdapter(ID)
_TERMINAL = {"completed", "partial", "failed", "cancelled", "interrupted"}


def _json(value: dict) -> str:
    checked = _JSON.validate_python(value)
    return orjson.dumps(checked, option=orjson.OPT_SORT_KEYS).decode()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class SessionStore:
    """Append immutable logical writes and expose consistent business versions.

    A single transaction assigns a version and publishes its summary and body.
    Replay checks the original digest even after the body has expired.
    """

    def __init__(self, location: str | Path):
        self.location = str(location)
        if not self.location or "\x00" in self.location:
            raise LogAgentError("invalid_argument", "session 数据库路径无效")
        Path(location).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.location, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        tables = {row[0] for row in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "run_sessions" in tables:
            self._db.close()
            raise LogAgentError("storage_version", "旧 Workflow 数据库需要显式迁移，不能隐去原 session")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA secure_delete=ON")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS session_headers (
                session_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
                created_at TEXT NOT NULL, policy TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_entries (
                session_id TEXT NOT NULL REFERENCES session_headers(session_id),
                version INTEGER NOT NULL, write_key TEXT NOT NULL,
                stage TEXT, scope TEXT NOT NULL, summary TEXT NOT NULL,
                body TEXT, availability TEXT NOT NULL, category TEXT, digest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(session_id, version), UNIQUE(session_id, write_key)
            );
        """)

    @contextmanager
    def _transaction(self):
        with self._lock:
            if self._db is None:
                raise LogAgentError("storage_closed", "session 数据库已关闭")
            owned = not self._db.in_transaction
            if owned:
                self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                if owned:
                    self._db.commit()
            except BaseException:
                if owned:
                    self._db.rollback()
                raise

    def create(self, session_id: str, workflow_id: str, policy: BackupPolicy) -> None:
        _ID.validate_python(session_id)
        _ID.validate_python(workflow_id)
        policy_json = _json(policy.model_dump(mode="json"))
        with self._transaction():
            row = self._db.execute(
                "SELECT * FROM session_headers WHERE session_id=?", (session_id,)
            ).fetchone()
            if row:
                if row["workflow_id"] != workflow_id or row["policy"] != policy_json:
                    raise LogAgentError("storage_conflict", "session 标识已绑定其他配置")
                return
            self._db.execute(
                "INSERT INTO session_headers VALUES(?,?,?,?)",
                (session_id, workflow_id, datetime.now(UTC).isoformat(), policy_json),
            )
            self.write(session_id, "created", stage=None, scope="parent", summary={"status": "created"})

    def write(
        self, session_id: str, key: str, *, stage: str | None, scope: str,
        summary: dict, body: dict | None = None, availability: str = "available", category: str | None = None,
    ) -> dict:
        encoded_summary = _json(summary)
        encoded_body = _json(body) if body is not None else None
        digest = _hash(_json({
            "stage": stage, "scope": scope, "summary": summary,
            "body": body, "availability": availability, "category": category,
        }))
        with self._transaction():
            previous = self._db.execute(
                "SELECT * FROM session_entries WHERE session_id=? AND write_key=?",
                (session_id, key),
            ).fetchone()
            if previous:
                if previous["digest"] != digest:
                    raise LogAgentError("storage_conflict", "幂等键对应的 session 内容不同")
                return self._entry(previous)
            if not self._db.execute(
                "SELECT 1 FROM session_headers WHERE session_id=?", (session_id,)
            ).fetchone():
                raise LogAgentError("session_not_found", "session 不存在")
            version = self._db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM session_entries WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
            self._db.execute(
                "INSERT INTO session_entries VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (session_id, version, key, stage, scope, encoded_summary, encoded_body,
                 availability, category, digest, datetime.now(UTC).isoformat()),
            )
            row = self._db.execute(
                "SELECT * FROM session_entries WHERE session_id=? AND version=?",
                (session_id, version),
            ).fetchone()
            return self._entry(row)

    @staticmethod
    def _entry(row: sqlite3.Row) -> dict:
        value = dict(row)
        try:
            value["summary"] = _JSON.validate_python(orjson.loads(value["summary"]))
            value["body"] = (
                _JSON.validate_python(orjson.loads(value["body"])) if value["body"] else None
            )
            if value["availability"] != "expired":
                expected = _hash(_json({
                    "stage": value["stage"], "scope": value["scope"],
                    "summary": value["summary"], "body": value["body"],
                    "availability": value["availability"], "category": value["category"],
                }))
                if expected != value["digest"]:
                    raise ValueError("Archive digest mismatch")
        except (ValueError, TypeError):
            raise LogAgentError("storage_corrupt", "session 业务存档损坏") from None
        return value

    def entry(self, session_id: str, key: str) -> dict | None:
        with self._transaction():
            row = self._db.execute(
                "SELECT * FROM session_entries WHERE session_id=? AND write_key=?",
                (session_id, key),
            ).fetchone()
            return self._entry(row) if row else None

    def entries(self, session_id: str, version: int | None = None) -> tuple[dict, list[dict]]:
        with self._transaction():
            header = self._db.execute(
                "SELECT * FROM session_headers WHERE session_id=?", (session_id,)
            ).fetchone()
            if header is None:
                raise LogAgentError("session_not_found", "session 不存在")
            if version is not None and (type(version) is not int or version < 1):
                raise LogAgentError("invalid_argument", "session version 必须为正整数")
            rows = self._db.execute(
                "SELECT * FROM session_entries WHERE session_id=? "
                "AND (? IS NULL OR version<=?) ORDER BY version",
                (session_id, version, version),
            ).fetchall()
            if not rows or (version is not None and rows[-1]["version"] != version):
                raise LogAgentError("version_not_found", "session 业务版本不存在")
            return dict(header), [self._entry(row) for row in rows]

    def session_ids(self) -> list[str]:
        with self._transaction():
            return [row[0] for row in self._db.execute(
                "SELECT session_id FROM session_headers ORDER BY created_at DESC,session_id"
            )]

    def expire(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        changed = 0
        with self._transaction():
            for sid in self.session_ids():
                header, entries = self.entries(sid)
                policy = BackupPolicy.model_validate_json(header["policy"])
                states = [e for e in entries if "status" in e["summary"] and e["scope"] in {"parent", "phase"}]
                if not states or policy.retention_days is None:
                    continue
                last = states[-1]
                if last["summary"]["status"] not in _TERMINAL:
                    continue
                if now < datetime.fromisoformat(last["created_at"]) + timedelta(days=policy.retention_days):
                    continue
                changed += self._db.execute(
                    "UPDATE session_entries SET body=NULL,availability='expired' "
                    "WHERE session_id=? AND body IS NOT NULL AND category IS NOT NULL", (sid,),
                ).rowcount
        return changed

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
