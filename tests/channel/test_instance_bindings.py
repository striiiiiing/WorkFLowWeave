"""Instance routing uses a locked memory cache; SQLite only restores it."""

import asyncio
import sqlite3
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock

import pytest

from workflowweave.channel.bindings import ChannelBindings, InstanceBinding
from workflowweave.errors import WorkFLowWeaveError


async def test_cached_binding_restores_without_adopting_legacy_peers(tmp_path, monkeypatch):
    path = tmp_path / "bindings.sqlite3"
    bindings = ChannelBindings(path)
    await bindings.start()
    await bindings.bind("legacy-peer", "legacy-session")
    assert bindings.instance("channel") == InstanceBinding()
    await bindings.bind_instance("channel", "current-session")
    await bindings.close()
    restored = ChannelBindings(path)
    await restored.start()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(restored._db, "execute", AsyncMock(side_effect=AssertionError("SQL read")))
            snapshot = restored.instance("channel")
            assert snapshot.session_id == "current-session"
            assert restored.instance("other-channel") == InstanceBinding()
            with pytest.raises(FrozenInstanceError):
                snapshot.session_id = "changed"
        assert await restored.current("legacy-peer") == "legacy-session"
    finally:
        await restored.close()


async def test_memory_updates_before_io_and_concurrent_writes_stay_ordered(tmp_path, monkeypatch):
    bindings = ChannelBindings(tmp_path / "bindings.sqlite3")
    await bindings.start()
    entered = asyncio.Event()
    release = asyncio.Event()
    execute = bindings._db.execute
    calls = []

    async def paused_execute(sql, parameters):
        calls.append(parameters[1])
        if parameters[1] == "session-a":
            entered.set()
            await release.wait()
        return await execute(sql, parameters)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(bindings._db, "execute", paused_execute)
            first = asyncio.create_task(bindings.bind_instance("channel", "session-a"))
            await asyncio.wait_for(entered.wait(), 1)
            assert bindings.instance("channel").session_id == "session-a"
            assert not first.done()
            second = asyncio.create_task(bindings.bind_instance("channel", "session-b"))
            await asyncio.sleep(0)
            assert not second.done()
            assert calls == ["session-a"]
            release.set()
            a, b = await asyncio.wait_for(asyncio.gather(first, second), 1)
        assert a.revision < b.revision
        assert bindings.instance("channel") == b
        async with bindings._db.execute("SELECT session FROM instance_bindings") as cursor:
            assert await cursor.fetchone() == ("session-b",)
    finally:
        release.set()
        await bindings.close()


async def test_failed_persistence_restores_session_and_invalidates_snapshots(tmp_path, monkeypatch):
    bindings = ChannelBindings(tmp_path / "bindings.sqlite3")
    await bindings.start()
    original = await bindings.bind_instance("channel", "session-a")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(bindings._db, "commit", AsyncMock(side_effect=sqlite3.OperationalError("disk full")))
            with pytest.raises(WorkFLowWeaveError) as error:
                await bindings.bind_instance("channel", "session-b")
            assert error.value.code == "storage_failed"
            assert isinstance(error.value.__cause__, sqlite3.OperationalError)
        recovered = bindings.instance("channel")
        assert recovered.session_id == "session-a"
        assert recovered.revision > original.revision + 1
        async with bindings._db.execute("SELECT session FROM instance_bindings") as cursor:
            assert await cursor.fetchone() == ("session-a",)
        changed = await bindings.bind_instance("channel", "session-b")
        assert changed.revision > recovered.revision
    finally:
        await bindings.close()


async def test_rebinding_original_session_does_not_revive_old_snapshot(tmp_path):
    bindings = ChannelBindings(tmp_path / "bindings.sqlite3")
    await bindings.start()
    try:
        first = await bindings.bind_instance("channel", "session-a")
        assert await bindings.bind_instance("channel", "session-a") == first
        await bindings.bind_instance("channel", None)
        returned = await bindings.bind_instance("channel", "session-a")
        assert first.session_id == returned.session_id
        assert first != returned
    finally:
        await bindings.close()


async def test_cancelled_binding_finishes_transaction_before_releasing_write_lock(tmp_path, monkeypatch):
    bindings = ChannelBindings(tmp_path / "bindings.sqlite3")
    await bindings.start()
    entered, release = asyncio.Event(), asyncio.Event()
    commit = bindings._db.commit

    async def delayed_commit():
        entered.set()
        await release.wait()
        await commit()

    try:
        with monkeypatch.context() as patch:
            patch.setattr(bindings._db, "commit", delayed_commit)
            task = asyncio.create_task(bindings.bind_instance("channel", "session-a"))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert bindings._lock.locked()
            assert bindings.instance("channel").session_id == "session-a"
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        async with bindings._db.execute("SELECT session FROM instance_bindings") as cursor:
            assert await cursor.fetchone() == ("session-a",)
        assert bindings.instance("channel").session_id == "session-a"
        assert not bindings._lock.locked()
    finally:
        release.set()
        await bindings.close()
