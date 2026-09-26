"""Small keyed input queue used by :class:`ChannelManager`.

The queue deliberately owns only admission and consumer lifetime.  Agent
state, request deduplication and delivery receipts remain in the injected
processor, which keeps this transport primitive usable by Web, QQ and test
channels without importing Agent code.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QueueOutcome:
    """Result published to the producer and optional work keeping the key busy."""

    value: Any
    settle: Awaitable[Any] | None = None


@dataclass(slots=True)
class _Item:
    payload: Any
    handler: Callable[[Any], Awaitable[QueueOutcome | Any]]
    accepted: asyncio.Future[Any]
    sequence: int
    switch: bool = False


class UnifiedQueue:
    """A bounded FIFO queue with one consumer per ``(source, peer, priority)``.

    Stop commands use a separate priority key, so cancellation can run while a
    normal consumer is waiting for an Agent turn.  The queue does not silently
    drop messages: a full key raises ``channel_queue_full`` at admission.
    """

    def __init__(self, *, capacity: int = 1000, idle_seconds: float = 600.0):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if not math.isfinite(idle_seconds) or idle_seconds <= 0:
            raise ValueError("idle_seconds must be positive and finite")
        self.capacity = capacity
        self.idle_seconds = idle_seconds
        self._queues: dict[Hashable, deque[_Item]] = defaultdict(deque)
        self._workers: dict[Hashable, asyncio.Task[None]] = {}
        self._active: dict[Hashable, _Item] = {}
        self._accepting = True
        self._lock = asyncio.Lock()
        self._changed = asyncio.Condition(self._lock)
        self._closing = False
        self._sequence = 0
        self._idle_since: dict[Hashable, float] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    @property
    def accepting(self) -> bool:
        return self._accepting

    def size(self, key: Hashable | None = None) -> int:
        if key is None:
            return sum(len(queue) for queue in self._queues.values())
        return len(self._queues.get(key, ()))

    def busy_count(self, *, channel_types: set[str] | None = None) -> int:
        """Count admitted work, including requests still settling their reply."""
        items = [*self._active.values(), *(item for queue in self._queues.values()
                                          for item in queue)]
        if channel_types is None:
            return len(items)
        return sum(
            1 for item in items
            if (config := item.payload.get("config")) is not None
            and config.channel in channel_types
        )

    async def submit(
        self,
        key: Hashable,
        payload: Any,
        handler: Callable[[Any], Awaitable[QueueOutcome | Any]],
        *,
        switch: bool = False,
        on_admit: Callable[[], Awaitable[None]] | None = None,
        on_interrupt: Callable[[Any], Awaitable[Any]] | None = None,
    ) -> Any:
        accepted = await self.admit(
            key, payload, handler, switch=switch, on_admit=on_admit,
            on_interrupt=on_interrupt,
        )
        return await asyncio.shield(accepted)

    async def admit(
        self,
        key: Hashable,
        payload: Any,
        handler: Callable[[Any], Awaitable[QueueOutcome | Any]],
        *,
        switch: bool = False,
        on_admit: Callable[[], Awaitable[None]] | None = None,
        on_interrupt: Callable[[Any], Awaitable[Any]] | None = None,
    ) -> asyncio.Future[Any]:
        loop = asyncio.get_running_loop()
        accepted = loop.create_future()
        async with self._changed:
            if not self._accepting or self._closing:
                raise RuntimeError("channel_manager_stopping")
            queue = self._queues[key]
            self._idle_since.pop(key, None)
            if len(queue) >= self.capacity:
                raise RuntimeError("channel_queue_full")
            if on_admit is not None:
                await on_admit()
            if on_interrupt is not None:
                for other_key, pending in list(self._queues.items()):
                    if other_key[:2] != key[:2] or other_key[2] == "stop":
                        continue
                    while pending:
                        older = pending[0]
                        result = await on_interrupt(older.payload)
                        pending.popleft()
                        if not older.accepted.done():
                            if isinstance(result, BaseException):
                                older.accepted.set_exception(result)
                            else:
                                older.accepted.set_result(result)
            self._sequence += 1
            queue.append(_Item(payload, handler, accepted, self._sequence, switch))
            worker = self._workers.get(key)
            if worker is None or worker.done():
                worker = asyncio.create_task(self._consume(key), name=f"channel:queue:{key}")
                self._workers[key] = worker
            if self._cleanup_task is None:
                self._cleanup_task = asyncio.create_task(
                    self._periodic_cleanup(), name="channel:queue:cleanup",
                )
            self._changed.notify_all()
        return accepted

    def _eligible(self, key: Hashable, item: _Item) -> bool:
        source, peer, priority = key
        if priority == "stop":
            return True
        older = [
            (other_key, other)
            for other_key, queue in self._queues.items()
            if other_key[:2] == (source, peer)
            for other in queue
            if other.sequence < item.sequence
        ]
        older.extend(
            (other_key, other) for other_key, other in self._active.items()
            if other_key[:2] == (source, peer) and other.sequence < item.sequence
        )
        if item.switch:
            return not any(other_key[2] != "stop" for other_key, _ in older)
        if any(other.switch or other_key[2] == "stop" for other_key, other in older):
            return False
        if priority == "command" and any(
            other_key[2] == "normal" for other_key, _ in older
        ):
            # Safe-boundary commands may act on a running turn ahead of the
            # next normal input, but must not jump an idle normal queue.
            return any(
                other_key[:2] == (source, peer) and other_key[2] == "normal"
                for other_key in self._active
            )
        return True

    async def _consume(self, key: Hashable) -> None:
        try:
            while True:
                async with self._changed:
                    while True:
                        queue = self._queues.get(key)
                        if not queue:
                            self._idle_since[key] = asyncio.get_running_loop().time()
                            self._workers.pop(key, None)
                            return
                        if self._eligible(key, queue[0]):
                            break
                        await self._changed.wait()
                    item = queue.popleft()
                    self._active[key] = item
                try:
                    outcome = await item.handler(item.payload)
                    if not isinstance(outcome, QueueOutcome):
                        outcome = QueueOutcome(outcome)
                    if not item.accepted.done():
                        item.accepted.set_result(outcome.value)
                    if outcome.settle is not None:
                        try:
                            await outcome.settle
                        except asyncio.CancelledError:
                            # Agent cancellation is a completed queue item;
                            # keep consuming later messages.  Cancellation of
                            # this worker itself still tears the queue down.
                            if asyncio.current_task().cancelling():
                                raise
                        except Exception:
                            # The accepted operation remains inspectable via its
                            # delivery receipt. A failed reply must not prevent
                            # this key from consuming subsequent messages.
                            logger.exception("channel_reply_settle_failed", extra={
                                "event": "channel_reply_settle_failed", "queue_key": str(key),
                            })
                except asyncio.CancelledError:
                    if not item.accepted.done():
                        item.accepted.cancel()
                    raise
                except Exception as exc:
                    if not item.accepted.done():
                        item.accepted.set_exception(exc)
                finally:
                    async with self._changed:
                        if self._active.get(key) is item:
                            self._active.pop(key, None)
                        self._changed.notify_all()
        finally:
            async with self._changed:
                if self._workers.get(key) is asyncio.current_task():
                    self._workers.pop(key, None)
                self._changed.notify_all()

    async def cleanup_idle(self) -> None:
        """Retire only queues with no worker or active request after the idle window."""
        now = asyncio.get_running_loop().time()
        async with self._changed:
            for key, since in list(self._idle_since.items()):
                if (now - since >= self.idle_seconds and not self._queues.get(key)
                        and key not in self._workers and key not in self._active):
                    self._queues.pop(key, None)
                    self._idle_since.pop(key, None)

    async def _periodic_cleanup(self) -> None:
        while True:
            await asyncio.sleep(60)
            await self.cleanup_idle()

    async def suspend(
        self, *, cancel_pending: bool = True,
        on_interrupt: Callable[[Any], Awaitable[Any]] | None = None,
    ) -> None:
        """Reject new input while allowing active consumers to settle."""
        async with self._changed:
            self._accepting = False
            pending = [item for queue in self._queues.values() for item in queue]
            if cancel_pending:
                results = ([await on_interrupt(item.payload) for item in pending]
                           if on_interrupt is not None else [
                               RuntimeError("channel_manager_suspended") for _ in pending
                           ])
                self._queues.clear()
                self._idle_since.clear()
            self._changed.notify_all()
        if cancel_pending:
            for item, result in zip(pending, results, strict=True):
                if not item.accepted.done():
                    if isinstance(result, BaseException):
                        item.accepted.set_exception(result)
                    else:
                        item.accepted.set_result(result)

    async def resume(self) -> None:
        async with self._changed:
            if not self._closing:
                self._accepting = True
                self._changed.notify_all()

    async def drain(self, budget_seconds: float) -> int:
        """Allow active consumers to finish after input admission has closed."""
        async with self._lock:
            workers = list(self._workers.values())
        if not workers:
            return 0
        _, pending = await asyncio.wait(workers, timeout=budget_seconds)
        return len(pending)

    async def close(self, *, cancel_pending: bool = True) -> None:
        async with self._changed:
            self._accepting = False
            self._closing = True
            workers = list(self._workers.values())
            pending = [item for queue in self._queues.values() for item in queue]
            if cancel_pending:
                self._queues.clear()
                self._idle_since.clear()
            self._changed.notify_all()
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None
        if cancel_pending:
            error = RuntimeError("channel_manager_stopping")
            for item in pending:
                if not item.accepted.done():
                    item.accepted.set_exception(error)
            for worker in workers:
                worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
