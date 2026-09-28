"""SQLite namespace 删除以父图提交为屏障，不把 stream chunk 当作提交。"""

import asyncio
import time

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from logagent.workflow import WorkflowService
from logagent.workflow.checkpoints import CheckpointNamespaces, WorkflowSqliteSaver
from tests.workflow.helpers import AI, Channel, Collector, snapshot


async def namespaces(saver):
    return {item.config["configurable"]["checkpoint_ns"] async for item in saver.alist(None)}


async def test_cleanup_waits_for_parent_commit_and_preserves_parent_replay(tmp_path):
    path = str(tmp_path / "checkpoints.sqlite3")
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        blocked = asyncio.Event()
        release = asyncio.Event()
        original = saver.aput

        async def put(config, checkpoint, metadata, new_versions):
            if (not config["configurable"].get("checkpoint_ns")
                    and checkpoint["channel_values"].get("phase", {}).get("stage") == "collect"
                    and not blocked.is_set()):
                blocked.set()
                await release.wait()
            return await original(config, checkpoint, metadata, new_versions)

        saver.aput = put
        w = WorkflowService(Collector(), AI(), Channel(), database=path, checkpointer=saver)
        try:
            await w.trigger(snapshot(channels=False), session_id="run")
            await asyncio.wait_for(blocked.wait(), 5)
            await w._cleanup.request("run")
            await w._cleanup.queue.join()
            assert any(name.startswith("collect:") for name in await namespaces(saver))
            assert not await w._cleanup.storage.completed("run")
            release.set()
            assert (await w.wait("run")).status == "completed"
            await w._cleanup.queue.join()
            assert await namespaces(saver) == {""}
            await w.resume("run", stage="analyze")
            assert (await w.wait("run")).status == "completed"
            assert len(w.collector_manager.calls) == 1
            assert len(w.ai_service.calls) == 4
        finally:
            release.set()
            await w.shutdown()


async def test_startup_sweep_keeps_interrupted_invocation(tmp_path):
    path = str(tmp_path / "checkpoints.sqlite3")
    ai = AI(block="second")
    w = WorkflowService(Collector(), ai, Channel(), database=path)
    await w.trigger(snapshot(channels=False, analysis_concurrency=1), session_id="run")
    await asyncio.wait_for(ai.started.wait(), 5)
    # Wait for the durable archive fact; entering the next coroutine is not a barrier.
    def first_archived():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, entries = w.session_store.entries("run")
            if any(entry["write_key"].startswith("analyze:item:first:epoch:") for entry in entries):
                return True
            time.sleep(0.001)
        return False
    assert await asyncio.to_thread(first_archived)
    await w.cancel("run")
    await w.wait("run")
    await w.shutdown()
    restored = WorkflowService(Collector(), AI(), Channel(), database=path)
    try:
        await restored.start()
        await restored._cleanup.queue.join()
        remaining = await namespaces(restored._checkpointer)
        assert any(ns.startswith("analyze:") for ns in remaining)
        assert not any(ns.startswith("collect:") for ns in remaining)
        await restored.resume("run")
        assert (await restored.wait("run")).status == "completed"
        assert [row[0] for row in restored.ai_service.calls] == ["second"]
        await restored._cleanup.queue.join()
        assert await namespaces(restored._checkpointer) == {""}
    finally:
        await restored.shutdown()


async def test_namespace_delete_is_atomic_and_does_not_delete_parent_or_neighbors(tmp_path):
    path = str(tmp_path / "checkpoints.sqlite3")
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        await saver.setup()
        async with saver.lock:
            for ns in ("", "collect:one", "collect:one_other"):
                await saver.conn.execute(
                    "INSERT INTO checkpoints(thread_id,checkpoint_ns,checkpoint_id) VALUES (?,?,?)",
                    ("run", ns, "checkpoint"),
                )
                await saver.conn.execute(
                    "INSERT INTO writes(thread_id,checkpoint_ns,checkpoint_id,task_id,idx,channel) VALUES (?,?,?,?,?,?)",
                    ("run", ns, "checkpoint", "task", 0, "items"),
                )
            await saver.conn.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON checkpoints "
                                     "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
            await saver.conn.commit()
        adapter = CheckpointNamespaces(saver)
        with pytest.raises(Exception, match="injected failure"):
            await adapter.delete("run", {"collect:one"})
        rows = await saver.conn.execute_fetchall("SELECT checkpoint_ns FROM writes")
        assert {row[0] for row in rows} == {"", "collect:one", "collect:one_other"}
        await saver.conn.execute("DROP TRIGGER reject_delete")
        await saver.conn.commit()
        await adapter.delete("run", {"collect:one"})
        for table in ("checkpoints", "writes"):
            rows = await saver.conn.execute_fetchall(f"SELECT checkpoint_ns FROM {table}")
            assert {row[0] for row in rows} == {"", "collect:one_other"}
        with pytest.raises(ValueError, match="parent"):
            await adapter.delete("run", {""})


async def test_saver_aput_writes_cancel_waits_for_commit_and_preserves_transaction(tmp_path):
    path = str(tmp_path / "workflow.sqlite3")
    async with WorkflowSqliteSaver.from_conn_string(path) as saver:
        await saver.setup()
        config = {"configurable": {
            "thread_id": "run", "checkpoint_ns": "", "checkpoint_id": "checkpoint-1",
        }}
        async with saver.lock:
            await saver.conn.execute(
                "INSERT INTO checkpoints(thread_id,checkpoint_ns,checkpoint_id) VALUES (?,?,?)",
                ("run", "", "checkpoint-1"),
            )
            await saver.conn.commit()

        commit_started = asyncio.Event()
        release_commit = asyncio.Event()
        original_commit = saver.conn.commit

        async def blocked_commit():
            commit_started.set()
            await release_commit.wait()
            return await original_commit()

        saver.conn.commit = blocked_commit
        pending = asyncio.create_task(
            saver.aput_writes(config, [("result", {"ok": True})], "task-1")
        )
        await asyncio.wait_for(commit_started.wait(), 5)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        release_commit.set()
        with pytest.raises(asyncio.CancelledError):
            await pending

        saver.conn.commit = original_commit
        rows = await saver.conn.execute_fetchall(
            "SELECT task_id,channel FROM writes WHERE thread_id=?", ("run",)
        )
        assert [(row[0], row[1]) for row in rows] == [("task-1", "result")]
        await saver.aput_writes(config, [("second", {"ok": True})], "task-2")


@pytest.mark.parametrize("restart", [False, True])
async def test_failed_cleanup_is_retried_at_next_boundary_or_startup(tmp_path, monkeypatch, caplog, restart):
    path = str(tmp_path / "checkpoints.sqlite3")
    delete = CheckpointNamespaces.delete
    fail = True

    async def unavailable(self, session_id, selected):
        if fail and selected:
            raise OSError("injected cleanup failure")
        await delete(self, session_id, selected)

    monkeypatch.setattr(CheckpointNamespaces, "delete", unavailable)
    w = WorkflowService(Collector(), AI(), Channel(), database=path)
    try:
        await w.trigger(snapshot(channels=False), session_id="run")
        assert (await w.wait("run")).status == "completed"
        await w._cleanup.queue.join()
        assert any(name for name in await namespaces(w._checkpointer))
        assert "injected cleanup failure" in caplog.text
        if restart:
            await w.shutdown()
            fail = False
            w = WorkflowService(Collector(), AI(), Channel(), database=path)
            await w.start()
        else:
            fail = False
            await w._cleanup.request("run")
        await w._cleanup.queue.join()
        assert await namespaces(w._checkpointer) == {""}
        assert (await w.get_session("run")).status == "completed"
    finally:
        await w.shutdown()
