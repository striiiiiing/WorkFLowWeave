"""Scheduling guarantees shared by Web, QQ and the local test transport."""

import asyncio

import pytest

from workflowweave.channel.unified_queue import QueueOutcome, UnifiedQueue

pytestmark = pytest.mark.asyncio


async def _until(predicate):
    async with asyncio.timeout(2):
        while not predicate():  # noqa: ASYNC110 - observe the queue between scheduling steps
            await asyncio.sleep(0.001)


async def test_session_switch_waits_for_earlier_messages_and_fences_later_ones():
    queue = UnifiedQueue()
    entered = asyncio.Event()
    release = asyncio.Event()
    order = []

    async def consume(name):
        order.append(name)
        if name == "A":
            entered.set()
            return QueueOutcome(name, release.wait())
        return name

    tasks = []
    try:
        tasks.append(asyncio.create_task(queue.submit(("test", "room", "normal"), "A", consume)))
        await entered.wait()
        tasks.append(asyncio.create_task(queue.submit(("test", "room", "normal"), "B", consume)))
        await _until(lambda: queue.size(("test", "room", "normal")) == 1)
        tasks.append(asyncio.create_task(queue.submit(
            ("test", "room", "command"), "new", consume, switch=True,
        )))
        await _until(lambda: queue.size(("test", "room", "command")) == 1)
        tasks.append(asyncio.create_task(queue.submit(("test", "room", "normal"), "C", consume)))
        await _until(lambda: queue.size(("test", "room", "normal")) == 2)
        assert order == ["A"]
        release.set()
        assert await asyncio.wait_for(asyncio.gather(*tasks), 2) == ["A", "B", "new", "C"]
        assert order == ["A", "B", "new", "C"]
    finally:
        release.set()
        await queue.close()


async def test_safe_boundary_command_runs_during_active_turn_before_next_message():
    queue = UnifiedQueue()
    entered = asyncio.Event()
    release = asyncio.Event()
    order = []

    async def consume(name):
        order.append(name)
        if name == "A":
            entered.set()
            return QueueOutcome(name, release.wait())
        return name

    try:
        a = asyncio.create_task(queue.submit(("test", "room", "normal"), "A", consume))
        await entered.wait()
        b = asyncio.create_task(queue.submit(("test", "room", "normal"), "B", consume))
        await _until(lambda: queue.size(("test", "room", "normal")) == 1)
        append = asyncio.create_task(queue.submit(("test", "room", "command"), "append", consume))
        assert await asyncio.wait_for(append, 2) == "append"
        assert order == ["A", "append"]
        release.set()
        assert await asyncio.wait_for(asyncio.gather(a, b), 2) == ["A", "B"]
    finally:
        release.set()
        await queue.close()


async def test_stop_preempts_active_turn_and_holds_later_input_until_settled():
    queue = UnifiedQueue()
    started = asyncio.Event()
    release = asyncio.Event()
    stopped = asyncio.Event()
    order = []

    async def consume(name):
        order.append(name)
        if name == "A":
            started.set()
            return QueueOutcome(name, release.wait())
        if name == "stop":
            stopped.set()
            return QueueOutcome(name, release.wait())
        return name

    try:
        a = asyncio.create_task(queue.submit(("test", "room", "normal"), "A", consume))
        await started.wait()
        stop = asyncio.create_task(queue.submit(("test", "room", "stop"), "stop", consume))
        await stopped.wait()
        later = asyncio.create_task(queue.submit(("test", "room", "normal"), "later", consume))
        await _until(lambda: queue.size(("test", "room", "normal")) == 1)
        assert order == ["A", "stop"]
        release.set()
        assert await asyncio.wait_for(asyncio.gather(a, stop, later), 2) == ["A", "stop", "later"]
    finally:
        release.set()
        await queue.close()


async def test_stop_rejects_full_queue_without_cutting_off_prior_input():
    queue = UnifiedQueue(capacity=1)
    active = asyncio.Event()
    release = asyncio.Event()
    interrupted = []

    async def consume(name):
        if name == "stop-active":
            active.set()
            return QueueOutcome(name, release.wait())
        return name

    async def interrupt(value):
        interrupted.append(value)
        return "interrupted"

    try:
        first = asyncio.create_task(queue.submit(("test", "room", "stop"), "stop-active", consume))
        await active.wait()
        second = asyncio.create_task(queue.submit(("test", "room", "stop"), "stop-waiting", consume))
        await _until(lambda: queue.size(("test", "room", "stop")) == 1)
        with pytest.raises(RuntimeError, match="channel_queue_full"):
            await queue.admit(
                ("test", "room", "stop"), "rejected", consume, on_interrupt=interrupt,
            )
        assert interrupted == []
        release.set()
        assert await asyncio.wait_for(asyncio.gather(first, second), 2) == [
            "stop-active", "stop-waiting",
        ]
    finally:
        release.set()
        await queue.close()


async def test_idle_cleanup_keeps_an_active_turn_and_retires_only_after_it_settles():
    queue = UnifiedQueue(idle_seconds=0.01)
    release = asyncio.Event()
    key = ("test", "room", "normal")

    async def consume(_):
        return QueueOutcome("accepted", release.wait())

    try:
        assert await queue.submit(key, "A", consume) == "accepted"
        await asyncio.sleep(0.02)
        await queue.cleanup_idle()
        assert key in queue._queues
        release.set()
        assert await queue.drain(2) == 0
        await asyncio.sleep(0.02)
        await queue.cleanup_idle()
        assert key not in queue._queues
    finally:
        release.set()
        await queue.close()
