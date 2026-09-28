"""SQLModel 业务存档：保存不可变逻辑写入及独立业务版本，不决定图执行进度。"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import URL, event, inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from logagent.errors import LogAgentError

from .models import (
    AnalysisBody,
    CheckpointSource,
    CollectionBody,
    EpochRetention,
    PromptVersion,
    ReportBody,
    ResultProvenance,
    SessionEntry,
    SessionHeader,
)


def _configure_sqlite(connection, _record) -> None:
    """仅连接配置使用驱动语句；业务表和查询由 SQLModel 定义。

    沿用 WAL/FULL、外键和安全删除设置；事务由 _transaction 显式开启。
    """
    connection.isolation_level = None
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        # Checkpoint writes use a separate SQLite connection.  Allow readers and
        # saver commits to wait for the short transaction boundary instead of
        # surfacing a transient lock error to a business query.
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA secure_delete=ON")
        cursor.execute("PRAGMA synchronous=FULL")
    finally:
        cursor.close()


class ArchiveDatabase:
    """连接、事务及关闭的唯一所有者。"""

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
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(self._engine, "connect", _configure_sqlite)
        try:
            if "run_sessions" in inspect(self._engine).get_table_names():
                raise LogAgentError(
                    "storage_version", "旧 Workflow 数据库需要显式迁移，不能隐去原 session"
                )
            SQLModel.metadata.create_all(
                self._engine,
                tables=[
                    model.__table__
                    for model in (
                        SessionHeader,
                        SessionEntry,
                        CheckpointSource,
                        CollectionBody,
                        AnalysisBody,
                        ReportBody,
                        PromptVersion,
                        ResultProvenance,
                        EpochRetention,
                    )
                ],
            )
        except BaseException:
            self._engine.dispose()
            raise

    @contextmanager
    def _transaction(self, *, immediate=True):
        """锁内复用外层 Session；写事务立即锁，读事务延迟获取锁。

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
                    session.connection().exec_driver_sql(
                        "BEGIN IMMEDIATE" if immediate else "BEGIN"
                    )
                    yield session
                    session.commit()
                except BaseException:
                    session.rollback()
                    raise
                finally:
                    self._session = None

    def close(self) -> None:
        """在实例锁内关闭连接；重复关闭不重复操作。"""
        with self._lock:
            if not self._closed:
                self._engine.dispose()
                self._closed = True
