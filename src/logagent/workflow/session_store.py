"""SQLite 业务存档：保存不可变逻辑写入及独立业务版本，不决定图执行进度。"""

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
    """校验 JSON 对象并按键排序编码，提供稳定的内容摘要输入。"""
    checked = _JSON.validate_python(value)
    return orjson.dumps(checked, option=orjson.OPT_SORT_KEYS).decode()


def _hash(value: str) -> str:
    """计算 UTF-8 文本的 SHA-256 摘要，用于完整性及幂等冲突检查。"""
    return hashlib.sha256(value.encode()).hexdigest()


class SessionStore:
    """以追加条目保存业务历史，事务内发布版本、摘要、正文和可用性。

    相同逻辑键重复提交复用原版本，内容冲突明确报错；正文过期后仍保留
    原摘要与幂等键，避免重放把旧正文重新插入。
    """

    def __init__(self, location: str | Path):
        """打开 SQLite 业务连接并初始化表和事务配置。

        启用 WAL、外键及完整同步；发现旧 run_sessions 表时要求显式迁移。
        连接可由工作线程使用，实例内通过可重入锁串行访问。
        """
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
        """在实例锁内复用现有事务，或开启并负责提交新的立即事务。

        嵌套调用不提前提交；异常时只有事务拥有者执行回滚，随后继续抛出异常。
        """
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
        """原子创建 session 头与 created 事件，重复创建相同绑定时直接返回。

        同一 session 已绑定不同 Workflow 或备份策略时抛出 storage_conflict。
        """
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
        """追加业务条目并返回存档内容，同一 session 内版本递增。

        稳定 key 已存在时比较原 digest：相同内容复用原版本，不同内容报冲突。
        新版本、摘要、正文及可用性在同一事务内发布。
        """
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
        """解码数据库条目并检查内容摘要；非法数据转换为 storage_corrupt。

        expired 条目正文已清除，保留的是清理前摘要，因此不再按当前正文验算。
        """
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
        """按 session 和稳定业务键读取单条存档，不存在时返回 None。"""
        with self._transaction():
            row = self._db.execute(
                "SELECT * FROM session_entries WHERE session_id=? AND write_key=?",
                (session_id, key),
            ).fetchone()
            return self._entry(row) if row else None

    def entries(self, session_id: str, version: int | None = None) -> tuple[dict, list[dict]]:
        """一致读取 session 头及截至指定版本的全部条目，按版本升序返回。

        省略 version 表示最新历史；session 或指定版本不存在时明确报错。
        """
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
        """按创建时间降序列出 session ID，同一创建时间按 ID 排序。"""
        with self._transaction():
            return [row[0] for row in self._db.execute(
                "SELECT session_id FROM session_headers ORDER BY created_at DESC,session_id"
            )]

    def expire(self, now: datetime | None = None) -> int:
        """按终态事件时间和保留天数清除到期业务正文，返回更新条目数。

        仅清理 category 非空的正文，保留管理事实、摘要、幂等键及 expired 原因；
        没有期限或最新状态未终结时不清理。调用方负责触发此操作。
        """
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
        """在实例锁内关闭连接；重复关闭不重复操作。"""
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None
