"""Append-only Agent facts and stable tool execution keys.

The JSONL file is the source of truth for user-visible execution facts.  The
in-memory indexes below are only rebuilt caches; they are never used to infer
an outcome when the file is unavailable or corrupt.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from logagent.agent.io import file_io
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
        self.lock_path = self.runtime / "History" / session_id / "events.lock"
        self._lock = asyncio.Lock()
        self._changed = asyncio.Condition()
        self._revision = 0
        self._loaded = False
        self._next_id = 1
        self._events: list[dict[str, Any]] = []
        self._tools: dict[str, dict[str, Any]] = {}

    async def initialize(self) -> None:
        await asyncio.to_thread(self._load)

    def _load(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock():
            self._replace_index(self._read_events_unlocked())
        self._loaded = True

    @classmethod
    def _parse_events(cls, raw: bytes) -> list[dict[str, Any]]:
        if raw and not raw.endswith(b"\n"):
            raise LogAgentError("event_log_corrupt", "事件文件末尾不是完整记录")
        events: list[dict[str, Any]] = []
        for expected_id, line in enumerate(raw.splitlines(), 1):
            event = json.loads(line)
            if type(event) is not dict or type(event.get("id")) is not int:
                raise ValueError("invalid event envelope")
            if event["id"] != expected_id:
                raise ValueError("event sequence gap")
            events.append(event)
        return events

    def _read_events_unlocked(self) -> list[dict[str, Any]]:
        try:
            raw = self.path.read_bytes() if self.path.exists() else b""
            return self._parse_events(raw)
        except LogAgentError:
            raise
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            raise LogAgentError("event_log_corrupt", "事件 JSONL 损坏，不能跳过记录继续") from None

    def _file_lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.lock_path.open("a+b")
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        class _Lock:
            def __enter__(_self):
                return stream

            def __exit__(_self, *_args):
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                stream.close()
        return _Lock()

    def _replace_index(self, events: list[dict[str, Any]]) -> None:
        self._events = []
        self._tools = {}
        self._next_id = 1
        for event in events:
            self._append_index(event)
            self._next_id += 1

    async def wait_for_events(self, after: int, *, wait_seconds: float = 15.0) -> list[dict[str, Any]]:
        """Return events after ``after`` without a polling gap.

        The check and subscription share the event-log revision.  An append
        racing with subscription either is observed by the immediate check or
        wakes the condition; the timeout is only a cross-process refresh and
        heartbeat boundary, never the correctness mechanism.
        """
        if type(after) is not int or after < 0:
            raise LogAgentError("invalid_argument", "事件游标必须是非负整数")
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while True:
            events = await self.replay(after)
            if events:
                return events
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            if remaining == 0:
                return []
            async with self._changed:
                revision = self._revision
                if self.latest_id > after or self._revision != revision:
                    continue
                try:
                    await asyncio.wait_for(self._changed.wait(), remaining)
                except TimeoutError:
                    return await self.replay(after)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()

    def _append_index(self, event: dict[str, Any]) -> None:
        self._events.append(event)
        key = event.get("tool_key")
        if key is None or event["type"] == "tool.queued":
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
            # Keep the durable public envelope explicit.  The flattened fields
            # remain for the internal recovery/index code and for compatibility
            # with existing history files; ``data`` is the transport payload
            # consumed by SSE clients.
            timestamp = self._timestamp()
            event = {
                "session_id": self.session_id,
                "turn_id": fields.get("turn_id"),
                "type": event_type,
                "at": timestamp,
                "data": dict(fields),
                "created_at": timestamp,
                **fields,
            }
            event, events = await file_io(self._append_locked, event)
            self._replace_index(events)
            self._revision += 1
            async with self._changed:
                self._changed.notify_all()
            return dict(event)

    def _append_locked(self, event: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with self._file_lock():
            events = self._read_events_unlocked()
            event = {"id": len(events) + 1, **event}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab") as stream:
                stream.write((json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())
            events.append(event)
            return event, events

    async def replay(self, after: int = 0) -> list[dict[str, Any]]:
        if type(after) is not int or after < 0:
            raise LogAgentError("invalid_argument", "事件游标必须是非负整数")
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load)
            events = await asyncio.to_thread(self._read_locked)
            self._replace_index(events)
            return [dict(event) for event in events if event["id"] > after]

    def _read_locked(self) -> list[dict[str, Any]]:
        with self._file_lock():
            return self._read_events_unlocked()

    async def reserve_tool(self, key: str, raw_arguments: Any, **metadata: Any) -> ToolReservation:
        if not key or not isinstance(key, str):
            raise LogAgentError("invalid_argument", "工具稳定键不能为空")
        arguments_digest = _digest(raw_arguments)
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load)
            reservation, events = await asyncio.to_thread(
                self._reserve_locked, key, arguments_digest, metadata,
            )
            self._replace_index(events)
            return reservation

    async def wait_for_tool(self, key: str, arguments: Any, *, wait_timeout: float | None = None,
                            poll_interval: float = 0.02) -> ToolReservation:
        """Wait for another process holding ``key`` to publish a terminal fact.

        ``reserve_tool`` deliberately only records ownership; a second worker
        must never execute the same side effect.  The JSONL file is the shared
        coordination point, so waiting workers re-read it under the file lock
        until the owner commits a result.  A timeout is an explicit diagnostic
        rather than permission to run the tool a second time.
        """
        if wait_timeout is not None and (wait_timeout < 0 or not isinstance(wait_timeout, (int, float))):
            raise LogAgentError("invalid_argument", "工具等待超时必须为非负数")
        deadline = None if wait_timeout is None else time.monotonic() + wait_timeout
        digest = _digest(arguments)
        while True:
            async with self._lock:
                if not self._loaded:
                    await asyncio.to_thread(self._load)
                reservation, events = await asyncio.to_thread(
                    self._reservation_from_file, key, digest,
                )
                self._replace_index(events)
            if reservation.status != "active":
                return reservation
            if deadline is not None and time.monotonic() >= deadline:
                raise LogAgentError("tool_wait_timeout", "等待活动工具结果超时",
                                    {"tool_key": key})
            await asyncio.sleep(poll_interval)

    def _reservation_from_file(self, key: str, arguments_digest: str):
        with self._file_lock():
            events = self._read_events_unlocked()
            item = None
            for event in events:
                if event.get("tool_key") != key or event["type"] == "tool.queued":
                    continue
                if item is None:
                    item = {"arguments_digest": event.get("arguments_digest"), "completed": None}
                if event["type"] in {"tool.completed", "tool.outcome_unknown"}:
                    item["completed"] = event
            if item is None:
                raise LogAgentError("tool_not_started", "等待的工具没有 started 记录")
            if item["arguments_digest"] != arguments_digest:
                raise LogAgentError("tool_key_conflict", "工具稳定键对应了不同参数")
            completed = item.get("completed")
            if completed is not None:
                return ToolReservation(key, arguments_digest, completed["type"],
                                       completed.get("result")), events
            return ToolReservation(key, arguments_digest, "active"), events

    def _reserve_locked(self, key: str, arguments_digest: str, metadata: dict) -> tuple[ToolReservation, list[dict[str, Any]]]:
        with self._file_lock():
            events = self._read_events_unlocked()
            tools: dict[str, dict[str, Any]] = {}
            for event in events:
                event_key = event.get("tool_key")
                if event_key is None or event["type"] == "tool.queued":
                    continue
                item = tools.setdefault(event_key, {
                    "arguments_digest": event.get("arguments_digest"),
                    "completed": None,
                })
                if event["type"] in {"tool.completed", "tool.outcome_unknown"}:
                    item["completed"] = event
            previous = tools.get(key)
            if previous is not None:
                if previous["arguments_digest"] != arguments_digest:
                    raise LogAgentError("tool_key_conflict", "工具稳定键对应了不同参数")
                completed = previous.get("completed")
                if completed is not None:
                    return ToolReservation(key, arguments_digest, completed["type"],
                                           completed.get("result")), events
                return ToolReservation(key, arguments_digest, "active"), events
            timestamp = self._timestamp()
            payload = {**metadata, "tool_key": key, "arguments_digest": arguments_digest}
            event = {"id": len(events) + 1, "session_id": self.session_id,
                     "turn_id": metadata.get("turn_id"), "type": "tool.started", "at": timestamp,
                     "data": payload, "created_at": timestamp, **payload}
            with self.path.open("ab") as stream:
                stream.write((json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())
            events.append(event)
            return ToolReservation(key, arguments_digest, "started"), events

    async def complete_tool(self, key: str, arguments: Any, result: dict[str, Any]) -> dict[str, Any]:
        arguments_digest = _digest(arguments)
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load)
            event, events, previous_result = await asyncio.to_thread(
                self._complete_locked, key, arguments_digest, result,
            )
            self._replace_index(events)
            if previous_result is not None:
                return previous_result
            return dict(event)

    def _complete_locked(self, key: str, arguments_digest: str, result: dict[str, Any]):
        with self._file_lock():
            events = self._read_events_unlocked()
            current = next((item for item in reversed(events)
                            if item.get("tool_key") == key and item["type"] == "tool.started"), None)
            if current is None:
                raise LogAgentError("tool_not_started", "工具完成事件缺少 started 记录")
            if current["arguments_digest"] != arguments_digest:
                raise LogAgentError("tool_key_conflict", "工具稳定键对应了不同参数")
            completed = next((item for item in reversed(events)
                              if item.get("tool_key") == key
                              and item["type"] in {"tool.completed", "tool.outcome_unknown"}), None)
            if completed is not None:
                return completed, events, completed.get("result") or {}
            timestamp = self._timestamp()
            payload = {**current.get("data", {}), "tool_key": key, "arguments_digest": arguments_digest,
                       "result": result}
            event = {"id": len(events) + 1, "session_id": self.session_id,
                     "turn_id": current.get("turn_id"), "type": "tool.completed", "at": timestamp,
                     "data": payload, "created_at": timestamp, **payload}
            with self.path.open("ab") as stream:
                stream.write((json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())
            events.append(event)
            return event, events, None

    async def mark_unknown(self, key: str, arguments: Any, *, reason: str = "outcome_unknown") -> dict[str, Any]:
        arguments_digest = _digest(arguments)
        async with self._lock:
            if not self._loaded:
                await asyncio.to_thread(self._load)
            event, events, previous = await asyncio.to_thread(
                self._unknown_locked, key, arguments_digest, reason,
            )
            self._replace_index(events)
            if previous is not None:
                return {"status": previous["type"], "result": previous.get("result")}
            return dict(event)

    def _unknown_locked(self, key: str, arguments_digest: str, reason: str):
        with self._file_lock():
            events = self._read_events_unlocked()
            current = next((item for item in reversed(events)
                            if item.get("tool_key") == key and item["type"] == "tool.started"), None)
            if current is None:
                raise LogAgentError("tool_not_started", "工具结果缺少 started 记录")
            if current["arguments_digest"] != arguments_digest:
                raise LogAgentError("tool_key_conflict", "工具稳定键对应了不同参数")
            completed = next((item for item in reversed(events)
                              if item.get("tool_key") == key
                              and item["type"] in {"tool.completed", "tool.outcome_unknown"}), None)
            if completed is not None:
                return completed, events, completed
            timestamp = self._timestamp()
            payload = {**current.get("data", {}), "tool_key": key, "arguments_digest": arguments_digest,
                       "result": {"status": "outcome_unknown", "reason": reason}}
            event = {"id": len(events) + 1, "session_id": self.session_id,
                     "turn_id": current.get("turn_id"), "type": "tool.outcome_unknown", "at": timestamp,
                     "data": payload, "created_at": timestamp, **payload}
            with self.path.open("ab") as stream:
                stream.write((json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())
            events.append(event)
            return event, events, None

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
