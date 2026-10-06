"""The sole session admission and active-turn task owner."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage

from workflowweave.agent.contracts import SessionView
from workflowweave.errors import WorkFLowWeaveError

logger = logging.getLogger(__name__)

def _new_id(prefix=""):
    return (prefix + uuid4().hex)[:80]

def _digest(value):
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

@dataclass(slots=True)
class ActiveTurn:
    session_id: str
    turn_id: str | None = None
    task: asyncio.Task | None = None
    compact_pending: bool = False
    compact_events: list[int] = field(default_factory=list)
    stop_requested: bool = False
    finishing: bool = False
    pending_appends: list[tuple[str, str, str, str]] = field(default_factory=list)

class TurnCoordinator:
    def __init__(self, repository):
        self.repository = repository
        self._current: dict[str, ActiveTurn] = {}
        self._turns: dict[str, ActiveTurn] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._admissions: set[asyncio.Task] = set()
        self._accepting = True
        self.admission_lock = asyncio.Lock()
        self.run = None

    def lock(self, session_id):
        return self._locks.setdefault(session_id, asyncio.Lock())

    def current(self, session_id) -> ActiveTurn:
        return self._current.setdefault(session_id, ActiveTurn(session_id))

    def active(self, session_id) -> bool:
        task = self.current(session_id).task
        return task is not None and not task.done()

    @property
    def tasks(self):
        return {key: value.task for key, value in self._turns.items()}

    @property
    def accepting(self) -> bool:
        return self._accepting

    async def pause_admission(self) -> int:
        """Stop new turns and return the number of currently active turns."""
        async with self.admission_lock:
            self._accepting = False
            return sum(1 for task in self._turns.values() if not task.task.done())

    def resume_admission(self) -> None:
        self._accepting = True

    async def close(self) -> None:
        async with self.admission_lock:
            self._accepting = False
        if self._admissions:
            await asyncio.shield(asyncio.gather(*self._admissions, return_exceptions=True))
        tasks = [turn.task for turn in self._turns.values() if not turn.task.done()]
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._turns.clear()
    async def _start_turn_locked(self, session: SessionView, text: str, *,
                                 request_id: str, turn_id: str | None = None,
                                 digest: str | None = None,
                                 compact_only: bool = False) -> dict[str, Any]:
        """Record and launch a turn while the admission/session locks are held."""
        turn_id = turn_id or _new_id("turn_")
        digest = digest or _digest(text)
        await self.repository.log(session.session_id).append("request.accepted", request_id=request_id,
                                 turn_id=turn_id, text_digest=digest)
        self.repository.requests(session.session_id)[request_id] = (turn_id, digest)
        self._current[session.session_id] = ActiveTurn(session.session_id, turn_id)
        ready = asyncio.Event()
        self.current(session.session_id).stop_requested = False
        self.current(session.session_id).finishing = False
        task = asyncio.create_task(self.run(session, turn_id, text, ready, compact_only=compact_only),
                                   name=f"agent:turn:{turn_id}")
        self.current(session.session_id).task = task
        self._turns[turn_id] = self.current(session.session_id)
        session.status, session.turn_id = "running", turn_id
        # Stop/close cannot cancel a coroutine before it enters its cleanup scope.
        await ready.wait()
        return {"session_id": session.session_id, "turn_id": turn_id, "deduplicated": False}

    async def submit(self, session_id: str, text: str, *, request_id: str) -> dict[str, Any]:
        return await self._accept_message(session_id, text, request_id=request_id, queue=False)

    async def submit_after_idle(self, session_id: str, text: str, *, request_id: str,
                                valid: Callable[[], bool] | None = None) -> dict[str, Any]:
        """Admit a normal channel message after the current turn settles.

        The public ``submit`` API intentionally keeps its historical
        ``session_busy`` response.  ChannelManager uses this entry point so
        messages accepted by a transport queue are not discarded merely
        because another source currently owns the model turn.
        """
        if not isinstance(text, str) or not text.strip():
            raise WorkFLowWeaveError("invalid_argument", "消息不能为空")
        if not isinstance(request_id, str) or not request_id.strip():
            raise WorkFLowWeaveError("invalid_argument", "request_id 不能为空")
        session = self.repository.get(session_id)
        digest = _digest(text)
        while True:
            wait_task = None
            async with self.admission_lock:
                async with self.lock(session.session_id):
                    if valid is not None and not valid():
                        raise WorkFLowWeaveError("message_interrupted", "消息在 Agent 准入前已停止")
                    previous = self.repository.requests(session.session_id).get(request_id)
                    if previous is not None:
                        if previous[1] != digest:
                            raise WorkFLowWeaveError("request_conflict", "request_id 已用于其他消息")
                        return {"session_id": session_id, "turn_id": previous[0], "deduplicated": True}
                    if not self._accepting:
                        raise WorkFLowWeaveError("agent_busy", "Agent 当前暂停接收新轮次")
                    if self.current(session.session_id).task is not None and not self.current(session.session_id).task.done():
                        wait_task = self.current(session.session_id).task
                    else:
                        return await self._start_turn_locked(
                            session, text, request_id=request_id, digest=digest,
                        )
            # wait() does not propagate the previous turn's cancellation to
            # this admission. A stop on another channel must not drop input
            # already waiting for the shared Agent session.
            await asyncio.wait({wait_task})

    async def append(self, session_id: str, text: str, *, request_id: str) -> dict[str, Any]:
        """Append a user message at the next safe model boundary.

        An idle session starts a normal turn immediately.  A running session
        records a durable command and injects it after the current model and
        its complete tool group, within the same owned turn.
        """
        return await self._accept_message(session_id, text, request_id=request_id, queue=True)

    async def _accept_message(self, session_id: str, text: str, *,
                              request_id: str, queue: bool) -> dict[str, Any]:
        task = asyncio.create_task(
            self._admit_message(session_id, text, request_id=request_id, queue=queue),
            name=f"agent:admit:{session_id}",
        )
        self._admissions.add(task)
        task.add_done_callback(self._admission_done)
        return await asyncio.shield(task)

    def _admission_done(self, task: asyncio.Task) -> None:
        self._admissions.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None and not isinstance(error, WorkFLowWeaveError):
                logger.error("Agent request admission failed", exc_info=error)

    async def _admit_message(self, session_id: str, text: str, *,
                             request_id: str, queue: bool) -> dict[str, Any]:
        """Serialize deduplication and publication for both message entrypoints."""
        if not isinstance(text, str) or not text.strip():
            raise WorkFLowWeaveError("invalid_argument", "消息不能为空")
        if not isinstance(request_id, str) or not request_id.strip():
            raise WorkFLowWeaveError("invalid_argument", "request_id 不能为空")
        session = self.repository.get(session_id)
        digest = _digest(text)
        async with self.admission_lock:
            async with self.lock(session.session_id):
                previous = self.repository.requests(session.session_id).get(request_id)
                if previous is not None:
                    if previous[1] != digest:
                        raise WorkFLowWeaveError("request_conflict", "request_id 已用于其他消息")
                    return {"session_id": session_id, "turn_id": previous[0], "deduplicated": True}
                if not self._accepting:
                    raise WorkFLowWeaveError("agent_busy", "Agent 当前暂停接收新轮次")
                if self.current(session.session_id).finishing and self.current(session.session_id).task is not None and not self.current(session.session_id).task.done():
                    # The final model boundary is already closed. Wait for
                    # its durable terminal fact before accepting a new turn.
                    await asyncio.wait({self.current(session.session_id).task})
                if self.current(session.session_id).task is not None and not self.current(session.session_id).task.done():
                    if not queue:
                        raise WorkFLowWeaveError("session_busy", "一个 session 同时只能运行一轮")
                    if self.current(session.session_id).stop_requested:
                        raise WorkFLowWeaveError("session_busy", "停止中的轮次不再接收命令")
                    turn_id = session.turn_id
                    event = await self.repository.log(session.session_id).append(
                        "command.queued", command="append", turn_id=session.turn_id,
                        queued_turn_id=turn_id, request_id=request_id,
                        text_digest=digest, text=text,
                    )
                    self.repository.requests(session.session_id)[request_id] = (turn_id, digest)
                    self.current(session.session_id).pending_appends.append((turn_id, text, request_id, digest))
                    return {"session_id": session_id, "turn_id": turn_id,
                            "status": "queued", "deduplicated": False,
                            "event_id": event["id"]}
                return await self._start_turn_locked(
                    session, text, request_id=request_id, digest=digest,
                )

    async def wait(self, turn_id: str) -> dict[str, Any]:
        task = self._turns.get(turn_id)
        if task is not None:
            return await asyncio.shield(task.task)
        for session in self.repository.views.values():
            terminal = next((event for event in reversed(self.repository.log(session.session_id).events)
                             if event.get("turn_id") == turn_id and event["type"] in {
                                 "turn.completed", "turn.failed", "turn.cancelled", "turn.interrupted",
                             }), None)
            if terminal is not None:
                return {"turn_id": turn_id, "status": terminal["type"].removeprefix("turn."),
                        "text": terminal.get("text", ""), "error": terminal.get("error")}
        raise WorkFLowWeaveError("turn_not_found", "Agent turn 不存在或已过期")

    async def cancel(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get(session_id)
        task = self.current(session.session_id).task
        if task is None or task.done():
            return self.repository.document(session)
        self.current(session.session_id).stop_requested = True
        if not task.cancelling():
            task.cancel()
        # The API acknowledges stop only after the turn has recorded its
        # terminal fact and released tool/scheduler resources.  A caller may
        # disconnect after this response without leaving a hidden background
        # cancellation race.
        await asyncio.shield(asyncio.gather(task, return_exceptions=True))
        return self.repository.document(session)

    async def compact(self, session_id: str) -> dict[str, Any]:
        session = self.repository.get(session_id)
        async with self.admission_lock, self.lock(session.session_id):
            if not self._accepting:
                raise WorkFLowWeaveError("agent_busy", "Agent 当前暂停接收命令")
            if self.current(session.session_id).task is not None and not self.current(session.session_id).task.done():
                if self.current(session.session_id).stop_requested:
                    raise WorkFLowWeaveError("session_busy", "停止中的轮次不再接收命令")
                event = await self.repository.log(session.session_id).append(
                    "command.queued", command="compact", turn_id=session.turn_id,
                )
                self.current(session.session_id).compact_pending = True
                self.current(session.session_id).compact_events.append(event["id"])
                return {"session_id": session_id, "status": "queued", "event_id": event["id"]}
            accepted = await self._start_turn_locked(
                session, "", request_id=_new_id("compact_"), compact_only=True,
            )
            return {**accepted, "status": "running"}

    async def _take_commands(self, session: SessionView, *, final=False):
        async with self.lock(session.session_id):
            if self.current(session.session_id).stop_requested:
                raise asyncio.CancelledError
            self.current(session.session_id).finishing = final and not self.current(session.session_id).pending_appends
            if not self.current(session.session_id).pending_appends and not self.current(session.session_id).compact_pending:
                return None
            appends = list(self.current(session.session_id).pending_appends)
            compact_events = list(self.current(session.session_id).compact_events)
            self.current(session.session_id).pending_appends.clear()
            self.current(session.session_id).compact_pending = False
            self.current(session.session_id).compact_events.clear()
            additions = []
            for turn_id, text, request_id, digest in appends:
                message_id = _new_id("message_")
                await self.repository.log(session.session_id).append("request.accepted", request_id=request_id,
                                         turn_id=turn_id, text_digest=digest)
                await self.repository.log(session.session_id).append("message.user", turn_id=turn_id,
                                         text=text, message_id=message_id, request_id=request_id)
                additions.append(HumanMessage(content=text, id=message_id))

        async def complete(*, compacted, error=None):
            event_type = "command.failed" if error is not None else "command.completed"
            for _, _, request_id, _ in appends:
                await self.repository.log(session.session_id).append(event_type, command="append",
                                         turn_id=session.turn_id, request_id=request_id, error=error)
            for event_id in compact_events:
                await self.repository.log(session.session_id).append(event_type, command="compact", error=error,
                                         turn_id=session.turn_id, command_event_id=event_id,
                                         compacted=compacted)
        return additions, bool(compact_events), complete

    async def _cancel_pending_commands(self, session: SessionView):
        for _, _, request_id, _ in self.current(session.session_id).pending_appends:
            await self.repository.log(session.session_id).append("command.cancelled", command="append",
                                     turn_id=session.turn_id, request_id=request_id)
        for event_id in self.current(session.session_id).compact_events:
            await self.repository.log(session.session_id).append("command.cancelled", command="compact",
                                     turn_id=session.turn_id, command_event_id=event_id)
        self.current(session.session_id).pending_appends.clear()
        self.current(session.session_id).compact_events.clear()
        self.current(session.session_id).compact_pending = False
