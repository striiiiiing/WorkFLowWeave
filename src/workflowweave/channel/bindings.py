"""Durable transport identity and request outcomes; no Agent history duplication."""

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

import aiosqlite

from workflowweave.errors import WorkFLowWeaveError


@dataclass(frozen=True)
class InstanceBinding:
    session_id: str | None = None
    revision: int = 0


class ChannelBindings:
    def __init__(self, path: Path):
        self.path = path
        self._db = None
        self._lock = asyncio.Lock()
        self._instances: dict[str, InstanceBinding] = {}
        self._cache_lock = RLock()

    async def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS peers (
                peer TEXT PRIMARY KEY, session TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ownership (
                peer TEXT NOT NULL, session TEXT NOT NULL, PRIMARY KEY (peer, session)
            );
            CREATE TABLE IF NOT EXISTS requests (
                peer TEXT NOT NULL, request TEXT NOT NULL, digest TEXT NOT NULL,
                response TEXT, delivery TEXT, status TEXT NOT NULL DEFAULT 'queued',
                operation_id TEXT, channel_id TEXT, operation TEXT,
                PRIMARY KEY (peer, request)
            );
            CREATE TABLE IF NOT EXISTS peer_migrations (
                legacy_peer TEXT PRIMARY KEY, peer TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS instance_bindings (
                channel_id TEXT PRIMARY KEY, session TEXT,
                revision INTEGER NOT NULL
            );
        """)
        async with self._db.execute(
            "SELECT channel_id, session, revision FROM instance_bindings"
        ) as cursor:
            instances = {
                ident: InstanceBinding(session, revision)
                for ident, session, revision in await cursor.fetchall()
            }
        with self._cache_lock:
            self._instances = instances
        async with self._db.execute("PRAGMA table_info(requests)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        if "status" not in columns:
            await self._db.execute(
                "ALTER TABLE requests ADD COLUMN status TEXT NOT NULL DEFAULT 'outcome_unknown'"
            )
        for column in ("operation_id", "channel_id", "operation"):
            if column not in columns:
                await self._db.execute(f"ALTER TABLE requests ADD COLUMN {column} TEXT")
        await self._db.execute(
            "UPDATE requests SET status='interrupted', response=?, delivery=? WHERE status='queued'",
            (json.dumps({"kind": "error", "error": {
                "code": "message_interrupted", "message": "服务重启前未处理的渠道输入已中断",
            }}, ensure_ascii=False), json.dumps({"status": "not_started"})),
        )
        await self._db.execute(
            "UPDATE requests SET status='outcome_unknown' WHERE status='processing'"
        )
        await self._db.commit()
        await self._mark_unfinished_deliveries()

    async def _mark_unfinished_deliveries(self):
        await self._db.execute(
            "UPDATE requests SET delivery=? WHERE response IS NOT NULL AND delivery IS NULL",
            (json.dumps({"status": "outcome_unknown", "error": {
                "code": "delivery_interrupted", "message": "渠道投递被中断，未确认送达，不自动重发",
            }}, ensure_ascii=False),),
        )
        await self._db.commit()

    async def close(self):
        if self._db is not None:
            await self._mark_unfinished_deliveries()
            await self._db.close()
            self._db = None

    async def current(self, peer):
        async with self._lock, self._db.execute(
            "SELECT session FROM peers WHERE peer=?", (peer,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    def instance(self, channel_id: str) -> InstanceBinding:
        """Read the startup-loaded cache; routing and sends never query SQLite."""
        with self._cache_lock:
            return self._instances.get(channel_id, InstanceBinding())

    async def bind_instance(self, channel_id: str, session_id: str | None) -> InstanceBinding:
        async with self._lock:
            previous = self.instance(channel_id)
            if previous.session_id == session_id:
                return previous
            binding = InstanceBinding(session_id, previous.revision + 1)
            with self._cache_lock:
                self._instances[channel_id] = binding
            persistence = asyncio.create_task(self._persist_instance(channel_id, binding, previous))
            cancelled = False
            # Cancelling an aiosqlite await cannot cancel SQL in its worker.
            # Keep the write lock until its transaction and cache agree.
            while not persistence.done():
                try:
                    await asyncio.shield(persistence)
                except asyncio.CancelledError:
                    cancelled = True
            persistence.result()
            if cancelled:
                raise asyncio.CancelledError
            return binding

    async def _persist_instance(self, channel_id, binding, previous):
        try:
            await self._db.execute(
                "INSERT INTO instance_bindings VALUES (?, ?, ?) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "session=excluded.session, revision=excluded.revision",
                (channel_id, binding.session_id, binding.revision),
            )
            await self._db.commit()
        except sqlite3.Error as exc:
            # Restoring the session must not revive old or transient snapshots.
            with self._cache_lock:
                self._instances[channel_id] = InstanceBinding(
                    previous.session_id, binding.revision + 1,
                )
            await self._db.rollback()
            raise WorkFLowWeaveError("storage_failed", "渠道对话绑定保存失败") from exc

    async def owns(self, peer, session):
        async with self._lock, self._db.execute(
            "SELECT 1 FROM ownership WHERE peer=? AND session=?", (peer, session),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def bind(self, peer, session):
        async with self._lock:
            await self._db.execute(
                "INSERT INTO peers VALUES (?, ?) ON CONFLICT(peer) DO UPDATE SET session=excluded.session",
                (peer, session),
            )
            await self._db.execute("INSERT OR IGNORE INTO ownership VALUES (?, ?)", (peer, session))
            await self._db.commit()

    async def migrate_peer(self, legacy_peer: str, peer: str):
        if legacy_peer == peer:
            return
        async with self._lock:
            async with self._db.execute(
                "SELECT peer FROM peer_migrations WHERE legacy_peer=?", (legacy_peer,),
            ) as cursor:
                mapping = await cursor.fetchone()
            if mapping is not None and mapping[0] != peer:
                raise WorkFLowWeaveError("request_conflict", "旧对话身份已映射到其他渠道")
            async with self._db.execute(
                "SELECT 1 FROM peers WHERE peer=? UNION SELECT 1 FROM requests WHERE peer=? LIMIT 1",
                (legacy_peer, legacy_peer),
            ) as cursor:
                if await cursor.fetchone() is None:
                    return
            async with self._db.execute(
                "SELECT old.session, current.session FROM peers AS old, peers AS current "
                "WHERE old.peer=? AND current.peer=?",
                (legacy_peer, peer),
            ) as cursor:
                row = await cursor.fetchone()
            if row is not None and row[0] != row[1]:
                raise WorkFLowWeaveError("request_conflict", "新旧对话身份绑定到不同 Agent 会话")
            async with self._db.execute(
                "SELECT 1 FROM requests AS old JOIN requests AS current "
                "ON old.request=current.request WHERE old.peer=? AND current.peer=? "
                "AND (old.digest!=current.digest OR "
                "COALESCE(old.response, '')!=COALESCE(current.response, '') OR "
                "COALESCE(old.operation_id, '')!=COALESCE(current.operation_id, '')) LIMIT 1",
                (legacy_peer, peer),
            ) as cursor:
                if await cursor.fetchone() is not None:
                    raise WorkFLowWeaveError("request_conflict", "新旧对话中同一消息 ID 的结果不一致")
            await self._db.execute(
                "INSERT OR IGNORE INTO peer_migrations(legacy_peer, peer) VALUES (?, ?)",
                (legacy_peer, peer),
            )
            await self._db.execute(
                "INSERT OR IGNORE INTO peers(peer, session) "
                "SELECT ?, session FROM peers WHERE peer=?", (peer, legacy_peer),
            )
            await self._db.execute(
                "INSERT OR IGNORE INTO ownership(peer, session) "
                "SELECT ?, session FROM ownership WHERE peer=?", (peer, legacy_peer),
            )
            await self._db.execute(
                "INSERT OR IGNORE INTO requests(peer, request, digest, response, delivery, status, "
                "operation_id, channel_id, operation) "
                "SELECT ?, request, digest, response, delivery, status, operation_id, "
                "channel_id, operation FROM requests WHERE peer=?",
                (peer, legacy_peer),
            )
            await self._db.commit()

    async def claim(self, peer, request, digest, *, operation_id=None,
                    channel_id=None, operation=None):
        async with self._lock:
            async with self._db.execute(
                "SELECT digest, response FROM requests WHERE peer=? AND request=?", (peer, request),
            ) as cursor:
                row = await cursor.fetchone()
            if row:
                if row[0] != digest:
                    raise WorkFLowWeaveError("request_conflict", "渠道消息 ID 对应了不同内容")
                if row[1] is None:
                    raise WorkFLowWeaveError("request_outcome_unknown", "消息曾开始处理但结果未保存，不自动重放")
                return json.loads(row[1])
            await self._db.execute(
                "INSERT INTO requests(peer, request, digest, operation_id, channel_id, operation) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (peer, request, digest, operation_id, channel_id, operation),
            )
            await self._db.commit()
            return None

    async def recovery_candidates(self):
        async with self._lock, self._db.execute(
            "SELECT peer, request, operation_id, channel_id, operation FROM requests "
            "WHERE status='outcome_unknown' AND response IS NULL "
            "AND operation_id IS NOT NULL",
        ) as cursor:
            return await cursor.fetchall()

    async def lookup(self, peer, request, digest):
        async with self._lock, self._db.execute(
            "SELECT digest, response FROM requests WHERE peer=? AND request=?",
            (peer, request),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        if row[0] != digest:
            raise WorkFLowWeaveError("request_conflict", "渠道消息 ID 对应了不同内容")
        if row[1] is None:
            raise WorkFLowWeaveError("request_outcome_unknown", "消息曾受理但结果未保存，不自动重放")
        return json.loads(row[1])

    async def processing(self, peer, request):
        async with self._lock:
            await self._db.execute(
                "UPDATE requests SET status='processing' WHERE peer=? AND request=?",
                (peer, request),
            )
            await self._db.commit()

    async def complete(self, peer, request, response, *, status=None, delivery=None):
        state = status or (
            "interrupted" if response.get("error", {}).get("code") == "message_interrupted"
            else "failed" if response.get("kind") == "error" else "completed"
        )
        async with self._lock:
            await self._db.execute(
                "UPDATE requests SET response=?, status=?, delivery=COALESCE(?, delivery) "
                "WHERE peer=? AND request=?",
                (json.dumps(response, ensure_ascii=False), state,
                 json.dumps(delivery, ensure_ascii=False) if delivery is not None else None,
                 peer, request),
            )
            await self._db.commit()

    async def set_status(self, peer, request, status):
        async with self._lock:
            await self._db.execute(
                "UPDATE requests SET status=? WHERE peer=? AND request=?",
                (status, peer, request),
            )
            await self._db.commit()

    async def delivered(self, peer, request, receipt):
        async with self._lock:
            await self._db.execute(
                "UPDATE requests SET delivery=? WHERE peer=? AND request=?",
                (json.dumps(receipt, ensure_ascii=False), peer, request),
            )
            await self._db.commit()

    async def outcome(self, peer, request):
        async with self._lock, self._db.execute(
            "SELECT response, delivery, status FROM requests WHERE peer=? AND request=?",
            (peer, request),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                raise WorkFLowWeaveError("request_not_found", "渠道消息不存在")
            return {"response": json.loads(row[0]) if row[0] else None,
                    "delivery": json.loads(row[1]) if row[1] else None,
                    "status": row[2]}
