import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from logagent.errors import LogAgentError
from logagent.models import BackupPolicy
from logagent.workflow import SessionStore, SessionView
from logagent.workflow.nodes import ArchiveRuntime, archive_node


@pytest.fixture
def store(tmp_path):
    value = SessionStore(tmp_path / "sessions.sqlite3")
    value.create("s", "w", BackupPolicy(retention_days=1))
    yield value
    value.close()


def write(store, key="phase:collect", text="原始业务正文"):
    return store.write("s", key, stage="collect", scope="phase", summary={"status": "running"},
                       body={"text": text}, category="collection")


def test_replay_and_conflict_are_atomic_and_version_is_per_session(store):
    first = write(store)
    assert first["version"] == 2
    assert write(store) == first
    with pytest.raises(LogAgentError, match="幂等键"):
        write(store, text="changed")
    _, entries = store.entries("s")
    assert entries[1:] == [first]
    assert write(store, "second")["version"] == 3


def test_concurrent_replays_and_branches_do_not_lose_updates(store):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: write(store), range(30)))
        list(pool.map(lambda i: write(store, str(i)), range(20)))
    assert {r["version"] for r in results} == {2}
    assert len(store.entries("s")[1]) == 22


def test_separate_connections_serialize_idempotent_writes(store):
    second = SessionStore(store.location)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, [store, second]))
        assert results[0] == results[1]
    finally:
        second.close()


def test_failed_transaction_does_not_publish_a_version(store):
    store._db.execute("CREATE TRIGGER fail BEFORE INSERT ON session_entries BEGIN SELECT RAISE(ABORT,'fault'); END")
    with pytest.raises(sqlite3.IntegrityError):
        write(store)
    store._db.execute("DROP TRIGGER fail")
    assert write(store)["version"] == 2


def test_expiry_retains_idempotence_and_management_records(store):
    old = write(store)
    store.write("s", "delivery", stage="notify", scope="notification", summary={}, body={"accepted": True})
    store.write("s", "finish", stage="finish", scope="phase", summary={"status": "completed"})
    assert store.expire(datetime.now(UTC) + timedelta(days=2)) == 1
    replay = write(store)
    assert replay["version"] == old["version"]
    assert replay["body"] is None and replay["availability"] == "expired"
    assert store.entry("s", "delivery")["body"] == {"accepted": True}
    assert len(store.entries("s")[1]) == 4


def test_corrupt_archives_are_reported_without_exposing_body(store):
    write(store)
    store._db.execute("UPDATE session_entries SET body=?", ('{"text":"secret"}',))
    with pytest.raises(LogAgentError) as caught:
        store.entry("s", "phase:collect")
    assert caught.value.code == "storage_corrupt"
    assert "secret" not in str(caught.value)


async def test_read_view_pins_version_and_never_uses_checkpoints(store):
    first = write(store)
    view = SessionView(store)
    frozen = await view.get_session("s")
    write(store, "other", "future")
    assert (await view.get_session("s", version=frozen.version)).version == first["version"]
    content = await view.get_phase_content("s", "collect", version=frozen.version)
    assert content.content == {"text": "原始业务正文"}
    assert len(await view.list_sessions()) == 1
    assert await view.list_sessions(exclude_session_id="s") == []
    with pytest.raises(LogAgentError):
        await view.get_session("s", version=99)
    tables = {r[0] for r in store._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "checkpoints" not in tables


async def test_one_node_factory_reuses_parent_and_child_writes(store):
    runtime = ArchiveRuntime(store, "s", BackupPolicy())
    calls = []
    async def operation(state):
        calls.append(state["item"])
        return {"text": state["item"]}
    for scope in ("parent", "child"):
        node = archive_node(runtime, scope=scope, stage="analyze", key=lambda state, scope=scope: f"{scope}:{state['item']}",
                            operation=operation, category="analysis")
        result = await node({"item": "one"})
        assert await node({"item": "one"}) == result
    assert calls == ["one", "one"]
    assert len(store.entries("s")[1]) == 3


async def test_disabled_bodies_only_survive_in_invocation_memory(store):
    runtime = ArchiveRuntime(store, "s", BackupPolicy(enabled=False))
    await runtime.save("body", stage="collect", scope="phase", summary={}, body={"text": "not-on-disk"}, category="collection")
    assert await runtime.read("body") == {"text": "not-on-disk"}
    assert store.entry("s", "body")["body"] is None
    with pytest.raises(LogAgentError):
        await ArchiveRuntime(store, "s", BackupPolicy(enabled=False)).read("body")


async def test_cancellation_waits_until_worker_transaction_finishes(store):
    import threading
    began, release = threading.Event(), threading.Event()
    original = store.write
    def slow(*args, **kwargs):
        began.set()
        release.wait(2)
        return original(*args, **kwargs)
    store.write = slow
    runtime = ArchiveRuntime(store, "s", BackupPolicy())
    task = asyncio.create_task(runtime.save("key", stage=None, scope="parent", summary={}))
    await asyncio.to_thread(began.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.entry("s", "key") is not None


async def test_created_session_is_immediately_queryable(store):
    record = await SessionView(store).get_session("s")
    assert record.status == "created" and record.version == 1
    assert record.snapshot_availability == "pending"


async def test_failed_backup_cannot_be_replayed_past_stop_policy(store):
    store.write("s", "failed", stage="analyze", scope="phase", summary={"backup_failed": True},
                availability="write_failed", category="analysis")
    async def operation(_):
        pytest.fail("Failed saved content must not repeat external work")
    node = archive_node(ArchiveRuntime(store, "s", BackupPolicy()), scope="phase", stage="analyze",
                        key="failed", operation=operation, category="analysis")
    with pytest.raises(LogAgentError) as caught:
        await node({})
    assert caught.value.code == "backup_failed"


def test_legacy_database_is_not_silently_hidden(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE run_sessions(session_id TEXT)")
    with pytest.raises(LogAgentError) as caught:
        SessionStore(path)
    assert caught.value.code == "storage_version"


def test_close_is_idempotent_and_use_after_close_is_explicit(store):
    store.close()
    store.close()
    with pytest.raises(LogAgentError) as caught:
        store.session_ids()
    assert caught.value.code == "storage_closed"


async def test_backup_failure_continue_records_missing_body_and_retains_runtime_value(store):
    store._db.execute("CREATE TRIGGER fail_body BEFORE INSERT ON session_entries WHEN NEW.body IS NOT NULL BEGIN SELECT RAISE(ABORT,'fault'); END")
    runtime = ArchiveRuntime(store, "s", BackupPolicy(on_failure="continue"))
    saved = await runtime.save("key", stage="analyze", scope="phase", summary={"status": "running"},
                               body={"text": "input"}, category="analysis")
    assert saved["availability"] == "write_failed" and saved["summary"]["backup_failed"]
    assert await runtime.read("key") == {"text": "input"}
    content = await SessionView(store).get_phase_content("s", "analyze", version=saved["version"])
    assert content.availability == "write_failed" and content.content is None


async def test_management_write_failure_always_propagates(store):
    store._db.execute("CREATE TRIGGER fail BEFORE INSERT ON session_entries BEGIN SELECT RAISE(ABORT,'fault'); END")
    runtime = ArchiveRuntime(store, "s", BackupPolicy(on_failure="continue"))
    with pytest.raises(sqlite3.IntegrityError):
        await runtime.save("intent", stage="notify", scope="notification", summary={}, body={"target": "mail"})
    assert len(store.entries("s")[1]) == 1


async def test_expiration_removes_all_historical_bodies_and_keeps_version(store):
    a = write(store, "phase:collect:1")
    b = write(store, "phase:collect:2", "new content")
    store.write("s", "finished", stage="finish", scope="phase", summary={"status": "completed"})
    store.expire(datetime.now(UTC) + timedelta(days=2))
    view = SessionView(store)
    for version in (a["version"], b["version"]):
        content = await view.get_phase_content("s", "collect", version=version)
        assert content.content is None and content.availability == "expired"
        assert (await view.get_session("s", version=version)).version == version
