import asyncio

import pytest

from workflowweave.agent.tools.scheduling import ToolScheduler


async def test_read_capacity_queues_until_a_slot_is_released():
    scheduler = ToolScheduler(2)
    entered = [asyncio.Event() for _ in range(3)]
    release = [asyncio.Event() for _ in range(3)]

    async def reader(index):
        async with scheduler.acquire("read"):
            entered[index].set()
            await release[index].wait()

    readers = [asyncio.create_task(reader(index)) for index in range(3)]
    await entered[0].wait()
    await entered[1].wait()
    await asyncio.sleep(0)

    assert scheduler.status == {
        "read_concurrency": 2,
        "write_concurrency": 1,
        "reading": 2,
        "writing": 0,
        "queued": 1,
    }
    assert not entered[2].is_set()

    release[0].set()
    await entered[2].wait()
    assert scheduler.status["reading"] == 2
    assert scheduler.status["queued"] == 0

    for event in release:
        event.set()
    await asyncio.gather(*readers)
    assert scheduler.status["reading"] == 0


async def test_exclusive_execution_blocks_reads_before_and_after_writer():
    scheduler = ToolScheduler(2)
    readers_entered = [asyncio.Event(), asyncio.Event()]
    release_readers = [asyncio.Event(), asyncio.Event()]

    async def reader(index):
        async with scheduler.acquire("read"):
            readers_entered[index].set()
            await release_readers[index].wait()

    active_readers = [
        asyncio.create_task(reader(index))
        for index in range(2)
    ]
    await readers_entered[0].wait()
    await readers_entered[1].wait()

    writer_entered = asyncio.Event()
    release_writer = asyncio.Event()

    async def writer():
        async with scheduler.acquire("exclusive"):
            writer_entered.set()
            await release_writer.wait()

    writer_task = asyncio.create_task(writer())
    await asyncio.sleep(0)
    assert scheduler.status["reading"] == 2
    assert scheduler.status["writing"] == 0
    assert scheduler.status["queued"] == 1
    assert not writer_entered.is_set()

    for event in release_readers:
        event.set()
    await writer_entered.wait()
    await asyncio.gather(*active_readers)
    assert scheduler.status["reading"] == 0
    assert scheduler.status["writing"] == 1

    blocked_reader_entered = asyncio.Event()

    async def blocked_reader():
        async with scheduler.acquire("read"):
            blocked_reader_entered.set()

    blocked_reader_task = asyncio.create_task(blocked_reader())
    await asyncio.sleep(0)
    assert scheduler.status["queued"] == 1
    assert not blocked_reader_entered.is_set()

    release_writer.set()
    await asyncio.gather(writer_task, blocked_reader_task)
    assert blocked_reader_entered.is_set()
    assert scheduler.status["reading"] == 0
    assert scheduler.status["writing"] == 0


async def test_cancelling_a_queued_operation_releases_its_queue_entry():
    scheduler = ToolScheduler(1)
    active_entered = asyncio.Event()
    release_active = asyncio.Event()

    async def active_reader():
        async with scheduler.acquire("read"):
            active_entered.set()
            await release_active.wait()

    active_task = asyncio.create_task(active_reader())
    await active_entered.wait()

    queued_task = asyncio.create_task(active_reader())
    await asyncio.sleep(0)
    assert scheduler.status["queued"] == 1

    queued_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued_task
    assert scheduler.status["queued"] == 0
    assert scheduler.status["reading"] == 1

    release_active.set()
    await active_task
    assert scheduler.status == {
        "read_concurrency": 1,
        "write_concurrency": 1,
        "reading": 0,
        "writing": 0,
        "queued": 0,
    }

    async with scheduler.acquire("exclusive"):
        assert scheduler.status["writing"] == 1
    assert scheduler.status["writing"] == 0


@pytest.mark.parametrize("execution", ["read", "exclusive"])
async def test_exception_releases_scheduler_lock(execution):
    scheduler = ToolScheduler(1)

    with pytest.raises(RuntimeError, match="body failed"):
        async with scheduler.acquire(execution):
            raise RuntimeError("body failed")

    assert scheduler.status == {
        "read_concurrency": 1,
        "write_concurrency": 1,
        "reading": 0,
        "writing": 0,
        "queued": 0,
    }
    async with scheduler.acquire(execution):
        pass
    assert scheduler.status["reading"] == 0
    assert scheduler.status["writing"] == 0
