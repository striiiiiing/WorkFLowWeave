"""Lifecycle-owned login sessions; platform authentication stays in plugins."""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

from workflowweave.errors import WorkFLowWeaveError

TERMINAL_STATES = {"connected", "failed"}


class LoginSession(Protocol):
    scope: str

    def snapshot(self) -> dict: ...

    async def start(self) -> None: ...

    async def verify(self, code: str) -> None: ...

    async def stop(self) -> None: ...


class ChannelLoginManager:
    def __init__(self):
        self._sessions: dict[str, LoginSession] = {}
        self._lock = asyncio.Lock()

    async def start(self, channel, options: dict) -> dict:
        factory = getattr(channel, "start_login", None)
        if factory is None:
            raise WorkFLowWeaveError("invalid_argument", "此渠道不支持网页登录")
        async with self._lock:
            session = await factory(options)
            if any(item.scope == session.scope and item.snapshot()["state"] not in TERMINAL_STATES
                   for item in self._sessions.values()):
                raise WorkFLowWeaveError("session_busy", "此状态目录已有登录会话，请先取消")
            ident = uuid.uuid4().hex
            await session.start()
            self._sessions[ident] = session
            return self.snapshot(ident)

    def _get(self, ident: str) -> LoginSession:
        session = self._sessions.get(ident)
        if session is None:
            raise WorkFLowWeaveError("request_not_found", "登录会话不存在或已结束")
        return session

    def snapshot(self, ident: str) -> dict:
        return {"session_id": ident, **self._get(ident).snapshot()}

    async def verify(self, ident: str, code: str) -> dict:
        await self._get(ident).verify(code)
        return self.snapshot(ident)

    async def cancel(self, ident: str) -> None:
        async with self._lock:
            await self._get(ident).stop()
            self._sessions.pop(ident)

    async def close(self) -> None:
        async with self._lock:
            await asyncio.gather(*(item.stop() for item in self._sessions.values()))
            self._sessions.clear()
