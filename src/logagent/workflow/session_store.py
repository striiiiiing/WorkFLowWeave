"""SQLModel 业务存档：保存不可变逻辑写入及独立业务版本，不决定图执行进度。"""

from __future__ import annotations

import hashlib
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import orjson
from pydantic import TypeAdapter
from sqlalchemy import URL, event, inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, func, select

from logagent.errors import LogAgentError
from logagent.models import ID, BackupPolicy, JSONObject

from .session_models import SessionEntry, SessionHeader

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


def _configure_sqlite(connection, _record) -> None:
    """仅连接配置使用驱动语句；业务表和查询由 SQLModel 定义。

    沿用 WAL/FULL、外键和安全删除设置；事务由 _transaction 显式开启。
    """
    connection.isolation_level = None
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA secure_delete=ON")
        cursor.execute("PRAGMA synchronous=FULL")
    finally:
        cursor.close()


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
        self._session: Session | None = None
        self._closed = False
        self._engine = create_engine(
            URL.create("sqlite", database=self.location),
            connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        event.listen(self._engine, "connect", _configure_sqlite)
        try:
            if "run_sessions" in inspect(self._engine).get_table_names():
                raise LogAgentError("storage_version", "旧 Workflow 数据库需要显式迁移，不能隐去原 session")
            SQLModel.metadata.create_all(
                self._engine, tables=[SessionHeader.__table__, SessionEntry.__table__]
            )
        except BaseException:
            self._engine.dispose()
            raise

    @contextmanager
    def _transaction(self):
        """锁内复用外层 Session；立即事务串行化不同实例的版本分配。

        SQLModel Session 只在最外层提交或回滚，嵌套业务写入不能提前发布。
        """
        with self._lock:
            if self._closed:
                raise LogAgentError("storage_closed", "session 数据库已关闭")
            if self._session is not None:
                yield self._session
                return
            with Session(self._engine) as session:
                self._session = session
                try:
                    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                    yield session
                    session.commit()
                except BaseException:
                    session.rollback()
                    raise
                finally:
                    self._session = None

    def create(self, session_id: str, workflow_id: str, policy: BackupPolicy) -> None:
        """原子创建 session 头与 created 事件，重复创建相同绑定时直接返回。

        同一 session 已绑定不同 Workflow 或备份策略时抛出 storage_conflict。
        """
        _ID.validate_python(session_id)
        _ID.validate_python(workflow_id)
        policy_json = _json(policy.model_dump(mode="json"))
        with self._transaction() as session:
            row = session.get(SessionHeader, session_id)
            if row:
                if row.workflow_id != workflow_id or row.policy != policy_json:
                    raise LogAgentError("storage_conflict", "session 标识已绑定其他配置")
                return
            session.add(SessionHeader(
                session_id=session_id, workflow_id=workflow_id,
                created_at=datetime.now(UTC).isoformat(), policy=policy_json,
            ))
            session.flush()
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
        with self._transaction() as session:
            previous = session.exec(select(SessionEntry).where(
                SessionEntry.session_id == session_id, SessionEntry.write_key == key,
            )).first()
            if previous:
                if previous.digest != digest:
                    raise LogAgentError("storage_conflict", "幂等键对应的 session 内容不同")
                return self._entry(previous)
            if session.get(SessionHeader, session_id) is None:
                raise LogAgentError("session_not_found", "session 不存在")
            latest = session.exec(select(func.max(SessionEntry.version)).where(
                SessionEntry.session_id == session_id,
            )).one()
            row = SessionEntry(
                session_id=session_id, version=(latest or 0) + 1, write_key=key,
                stage=stage, scope=scope, summary=encoded_summary, body=encoded_body,
                availability=availability, category=category, digest=digest,
                created_at=datetime.now(UTC).isoformat(),
            )
            session.add(row)
            session.flush()
            return self._entry(row)

    @staticmethod
    def _entry(row: SessionEntry) -> dict:
        """解码数据库条目并检查内容摘要；非法数据转换为 storage_corrupt。

        expired 条目正文已清除，保留的是清理前摘要，因此不再按当前正文验算。
        """
        value = row.model_dump()
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
        with self._transaction() as session:
            row = session.exec(select(SessionEntry).where(
                SessionEntry.session_id == session_id, SessionEntry.write_key == key,
            )).first()
            return self._entry(row) if row else None

    def entries(self, session_id: str, version: int | None = None) -> tuple[dict, list[dict]]:
        """一致读取 session 头及截至指定版本的全部条目，按版本升序返回。"""
        with self._transaction() as session:
            header = session.get(SessionHeader, session_id)
            if header is None:
                raise LogAgentError("session_not_found", "session 不存在")
            if version is not None and (type(version) is not int or version < 1):
                raise LogAgentError("invalid_argument", "session version 必须为正整数")
            statement = select(SessionEntry).where(SessionEntry.session_id == session_id)
            if version is not None:
                statement = statement.where(SessionEntry.version <= version)
            rows = session.exec(statement.order_by(SessionEntry.version)).all()
            if not rows or (version is not None and rows[-1].version != version):
                raise LogAgentError("version_not_found", "session 业务版本不存在")
            return header.model_dump(), [self._entry(row) for row in rows]

    def session_ids(self) -> list[str]:
        """按创建时间降序列出 session ID，同一创建时间按 ID 排序。"""
        with self._transaction() as session:
            return list(session.exec(select(SessionHeader.session_id).order_by(
                SessionHeader.created_at.desc(), SessionHeader.session_id,
            )).all())

    def expire(self, now: datetime | None = None) -> int:
        """按终态事件时间和保留天数清除到期业务正文，返回更新条目数。

        仅清理 category 非空的正文，保留管理事实、摘要、幂等键及 expired 原因；
        没有期限或最新状态未终结时不清理。调用方负责触发此操作。
        """
        now = now or datetime.now(UTC)
        changed = 0
        with self._transaction() as session:
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
                rows = session.exec(select(SessionEntry).where(
                    SessionEntry.session_id == sid,
                    SessionEntry.body.is_not(None), SessionEntry.category.is_not(None),
                )).all()
                for row in rows:
                    row.body = None
                    row.availability = "expired"
                    session.add(row)
                changed += len(rows)
        return changed

    def close(self) -> None:
        """在实例锁内关闭连接；重复关闭不重复操作。"""
        with self._lock:
            if not self._closed:
                self._engine.dispose()
                self._closed = True
