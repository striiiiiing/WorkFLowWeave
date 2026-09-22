"""Append-only Agent facts and stable tool execution keys.

The JSONL file is the source of truth for user-visible execution facts.  The
in-memory indexes below are only rebuilt caches; they are never used to infer
an outcome when the file is unavailable or corrupt.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from logagent.errors import LogAgentError


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolReservation:
    key: str
    arguments_digest: str
    status: str
    result: dict[str, Any] | None = None


class EventLog:
    """Durable event log for one Agent session.

    A short append lock covers sequence allocation and ``fsync`` only.  Tool
    work is performed by callers after ``reserve_tool`` returns, so the log
    lock never serializes model or filesystem operations.
    """

    def __init__(self, runtime: Path, session_id: str):
        self.runtime = runtime.absolute()
        self.session_id = session_id
        self.path = self.runtime / "History" / session_id / "events.jsonl"
        self._lock = asyncio.Lock()
        self._loaded = False
        self._next_id = 1
        self._events: list[dict[str, Any]] = []
        self._tools: dict[str, dict[str, Any]] = {}

    async def initialize(self) -> None:
        await asyncio.to_thread(self._load)

    def _load(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._loaded = True
            return
        try:
            raw = self.path.read_bytes()
            if raw and not raw.endswith(b"\n"):
                raise LogAgentError("event_log_corrupt", "事件文件末尾不是完整记录")
            for line in raw.splitlines():
                event = json.loads(line)
                if type(event) is not dict or type(event.get("id")) is not int:
                    raise ValueError("invalid event envelope")
                if event["id"] != self._next_id:
                    raise ValueError("event sequence gap")
                self._append_index(event)
                self._next_id += 1
            self._loaded = True
        except LogAgentError:
            raise
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            raise LogAgentError("event_log_corrupt", "事件 JSONL 损坏，不能跳过记录继续") from None

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()

    def _append_index(self, event: dict[str, Any]) -> None:
        self._events.append(event)
        key = event.get("tool_key")
        if key is None:
            return
        current = self._tools.setdefault(key, {
            "arguments_digest": event.get("arguments_digest"),
            "started": None,
            "completed": None,
        })
        if event["type"] == "tool.started":
            current["started"] = event
        elif event["type"] == "tool.completed":
            current["completed"] = event
        elif event["type"] == "tool.outcome_unknown":
            current["completed"] = event

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()

    async def append(self, event_type: str, **fields: Any) -> dict[str, Any]:
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load)
            event = {"id": self._next_id, "type": event_type,
                     "created_at": self._timestamp(), **fields}
            await asyncio.to_thread(self._write, event)
            self._append_index(event)
            self._next_id += 1
            return dict(event)

    def _write(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as stream:
            stream.write((json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())

    async def replay(self, after: int = 0) -> list[dict[str, Any]]:
        if type(after) is not int or after < 0:
            raise LogAgentError("invalid_argument", "事件游标必须是非负整数")
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load)
            return [dict(event) for event in self._events if event["id"] > after]

    async def reserve_tool(self, key: str, arguments: Any) -> ToolReservation:
        if not key or not isinstance(key, str):
            raise LogAgentError("invalid_argument", "工具稳定键不能为空")
        arguments_digest = _digest(arguments)
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load)
            previous = self._tools.get(key)
            if previous is not None:
                if previous["arguments_digest"] != arguments_digest:
                    raise LogAgentError("tool_key_conflict", "工具稳定键对应了不同参数")
                completed = previous.get("completed")
                if completed is not None:
                    result = completed.get("result")
                    return ToolReservation(key, arguments_digest, completed["type"], result)
                return ToolReservation(key, arguments_digest, "active")
            event = {"id": self._next_id, "type": "tool.started",
                     "created_at": self._timestamp(), "tool_key": key,
                     "arguments_digest": arguments_digest}
            await asyncio.to_thread(self._write, event)
            self._append_index(event)
            self._next_id += 1
            return ToolReservation(key, arguments_digest, "started")

    async def complete_tool(self, key: str, arguments: Any, result: dict[str, Any]) -> dict[str, Any]:
        arguments_digest = _digest(arguments)
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load)
            previous = self._tools.get(key)
            if previous is None:
                raise LogAgentError("tool_not_started", "工具完成事件缺少 started 记录")
            if previous["arguments_digest"] != arguments_digest:
                raise LogAgentError("tool_key_conflict", "工具稳定键对应了不同参数")
            completed = previous.get("completed")
            if completed is not None:
                return completed.get("result") or {}
            event = {"id": self._next_id, "type": "tool.completed",
                     "created_at": self._timestamp(), "tool_key": key,
                     "arguments_digest": arguments_digest, "result": result}
            await asyncio.to_thread(self._write, event)
            self._append_index(event)
            self._next_id += 1
            return dict(event)

    async def mark_unknown(self, key: str, arguments: Any, *, reason: str = "outcome_unknown") -> dict[str, Any]:
        arguments_digest = _digest(arguments)
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load)
            previous = self._tools.get(key)
            if previous is None:
                raise LogAgentError("tool_not_started", "工具结果缺少 started 记录")
            if previous["arguments_digest"] != arguments_digest:
                raise LogAgentError("tool_key_conflict", "工具稳定键对应了不同参数")
            completed = previous.get("completed")
            if completed is not None:
                return {"status": completed["type"], "result": completed.get("result")}
            event = {"id": self._next_id, "type": "tool.outcome_unknown",
                     "created_at": self._timestamp(), "tool_key": key,
                     "arguments_digest": arguments_digest,
                     "result": {"status": reason}}
            await asyncio.to_thread(self._write, event)
            self._append_index(event)
            self._next_id += 1
            return dict(event)

    async def recover_interrupted(self) -> list[str]:
        """Mark started calls without terminal facts after a process restart."""
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load)
            keys = [key for key, value in self._tools.items()
                    if value.get("started") is not None and value.get("completed") is None]
        for key in keys:
            value = self._tools[key]
            await self.append("tool.outcome_unknown", tool_key=key,
                              arguments_digest=value["arguments_digest"],
                              result={"status": "outcome_unknown", "reason": "interrupted"})
        return keys

    @property
    def latest_id(self) -> int:
        return self._next_id - 1

    @property
    def events(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events]
