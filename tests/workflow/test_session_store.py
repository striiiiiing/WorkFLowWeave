"""Workflow 业务存档和只读版本视图测试。

使用真实临时 SQLite/SQLModel 存储，验证幂等重放、冲突、并发版本分配、
事务回滚、正文保留和过期清理；故障注入检查备份策略、管理写入失败及取消。
同时核对旧 schema 兼容和内存库线程访问，业务版本不依赖执行 checkpoint。
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import URL, inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine, select, text

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import BackupPolicy
from workflowweave.workflow.storage.facts import SessionStore
from workflowweave.workflow.storage.models import CollectionBody, SessionEntry, SessionHeader
from workflowweave.workflow.storage.sessions import SessionView
from workflowweave.workflow.stream.subscriptions.checkpoints import CheckpointArchive, commit


@pytest.fixture
def store(tmp_path):
    value = SessionStore(tmp_path / "sessions.sqlite3")
    value.create("s", "w", BackupPolicy(collection_retention_days=1))
    yield value
    value.close()


def _ddl(store, statement):
    with store._transaction() as session:
        session.connection().exec_driver_sql(statement)


def write(store, key="phase:collect", text="原始业务正文"):
    return store.write("s", key, stage="collect", scope="phase", summary={"status": "running", "execution_epoch": "epoch"},
                       body={"text": text}, category="collection")


def test_replay_and_conflict_are_atomic_and_version_is_per_session(store):
    first = write(store)
    assert first["version"] == 2
    assert write(store) == first
    with pytest.raises(WorkFLowWeaveError, match="幂等键"):
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
    _ddl(store, "CREATE TRIGGER fail BEFORE INSERT ON session_entries BEGIN SELECT RAISE(ABORT,'fault'); END")
    with pytest.raises(IntegrityError):
        write(store)
    _ddl(store, "DROP TRIGGER fail")
    assert write(store)["version"] == 2


def test_expiry_retains_idempotence_and_management_records(store):
    old = write(store)
    store.write("s", "delivery", stage="notify", scope="notification", summary={}, body={"accepted": True})
    store.write("s", "finish", stage="finish", scope="phase", summary={"status": "completed", "execution_epoch": "epoch"})
    assert store.expire(datetime.now(UTC) + timedelta(days=2)) == 1
    replay = write(store)
    assert replay["version"] == old["version"]
    assert replay["body"] is None and replay["availability"] == "expired"
    assert store.entry("s", "delivery")["body"] == {"accepted": True}
    assert len(store.entries("s")[1]) == 5


def test_corrupt_archives_are_reported_without_exposing_body(store):
    write(store)
    with store._transaction() as session:
        for row in session.exec(select(CollectionBody)).all():
            row.content = '{"text":"secret"}'
            session.add(row)
    with pytest.raises(WorkFLowWeaveError) as caught:
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
    with pytest.raises(WorkFLowWeaveError):
        await view.get_session("s", version=99)
    tables = set(inspect(store._engine).get_table_names())
    assert "checkpoints" not in tables


async def test_archive_reuses_parent_and_child_facts_without_publishing_twice(store):
    published = []
    async def publish(record):
        published.append(record)
    archive = CheckpointArchive(None, store, SessionView(store), publish)
    for scope in ("parent", "child"):
        args = ("s", f"{scope}:one", "analyze", scope, "analysis", BackupPolicy(),
                {"item_status": "success", "item_id": "one"}, {"text": "one"}, None)
        result = await archive._write(*args)
        assert await archive._write(*args) == result
    assert len(published) == 1
    assert len(store.entries("s")[1]) == 3


def test_existing_write_rejects_conflicting_recovery_payload(store):
    saved = write(store)
    assert store.existing_write(
        "s", "phase:collect", stage="collect", scope="phase",
        summary={"status": "running", "execution_epoch": "epoch"},
        body={"text": "原始业务正文"}, category="collection",
    ) == saved
    with pytest.raises(WorkFLowWeaveError, match="幂等键"):
        store.existing_write(
            "s", "phase:collect", stage="collect", scope="phase",
            summary={"status": "running", "execution_epoch": "epoch"},
            body={"text": "changed"}, category="collection",
        )


async def test_disabled_archive_bodies_are_explicitly_not_saved(store):
    async def publish(record):
        pass
    archive = CheckpointArchive(None, store, SessionView(store), publish)
    await archive._write("s", "body", "collect", "collect", "collection", BackupPolicy(enabled=False),
                         {"item_status": "success", "item_id": "body"}, {"text": "not-on-disk"}, None)
    assert store.entry("s", "body")["body"] is None
    assert store.entry("s", "body")["availability"] == "not_saved"
    with store._transaction() as session:
        assert session.exec(select(CollectionBody)).all() == []


async def test_cancellation_waits_until_worker_transaction_finishes(store):
    import threading
    began, release = threading.Event(), threading.Event()
    original = store.write
    def slow(*args, **kwargs):
        began.set()
        release.wait(2)
        return original(*args, **kwargs)
    store.write = slow
    task = asyncio.create_task(commit(store.write, "s", "key", stage=None, scope="parent", summary={}))
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


async def test_mcp_binding_ignores_legacy_collector_sources(store):
    from workflowweave.models import AIConfig, SourceConfig, WorkflowDefinition, WorkflowSnapshot

    legacy = WorkflowSnapshot(
        workflow=WorkflowDefinition(
            id="legacy-workflow", sources=["legacy"],
            analyses=[{"user_prompt": "analyze input", "id": "analysis", "ai": "ai", "model": "model"}],
        ),
        sources={"legacy": SourceConfig(id="legacy", collector="mock")},
        ai={"ai": AIConfig(id="ai", provider="mock", models={"model": {}})},
        channels={}, created_at=datetime.now(UTC),
    )
    store.write(
        "s", "snapshot", stage=None, scope="configuration", summary={},
        body={"snapshot": legacy.model_dump(mode="json")}, category="snapshot",
    )
    assert await SessionView(store).mcp_binding("s") == {"servers": {}, "sources": []}


async def test_failed_archive_stop_preserves_error_without_fabricating_business_result(store):
    _ddl(store, "CREATE TRIGGER fail_body BEFORE INSERT ON workflow_analysis_bodies BEGIN SELECT RAISE(ABORT,'fault'); END")
    async def publish(record):
        pass
    archive = CheckpointArchive(None, store, SessionView(store), publish)
    with pytest.raises(WorkFLowWeaveError) as caught:
        await archive._write("s", "failed", "analyze", "analyze", "analysis", BackupPolicy(),
                             {"item_id": "one", "item_status": "success"}, {"text": "value"}, None)
    assert caught.value.code == "backup_failed"
    assert store.entry("s", "failed") is None
    assert store.entry("s", "archive_failed:failed")["scope"] == "archive_error"


def test_legacy_database_is_not_silently_hidden(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    engine = create_engine(URL.create("sqlite", database=str(path)))
    try:
        with Session(engine) as session:
            session.execute(text("CREATE TABLE run_sessions(session_id TEXT)"))
            session.commit()
    finally:
        engine.dispose()
    with pytest.raises(WorkFLowWeaveError) as caught:
        SessionStore(path)
    assert caught.value.code == "storage_version"


def test_close_is_idempotent_and_use_after_close_is_explicit(store):
    store.close()
    store.close()
    with pytest.raises(WorkFLowWeaveError) as caught:
        store.session_ids()
    assert caught.value.code == "storage_closed"


async def test_backup_failure_continue_records_error_and_reconciliation_fills_one_result(store):
    _ddl(store, "CREATE TRIGGER fail_body BEFORE INSERT ON workflow_analysis_bodies BEGIN SELECT RAISE(ABORT,'fault'); END")
    async def publish(record):
        pass
    archive = CheckpointArchive(None, store, SessionView(store), publish)
    args = ("s", "key", "analyze", "analyze", "analysis", BackupPolicy(on_failure="continue"),
            {"item_id": "one", "item_status": "success"}, {"text": "input"}, None)
    saved = await archive._write(*args)
    assert saved["scope"] == "archive_error" and saved["summary"]["result_key"] == "key"
    assert store.entry("s", "key") is None and store.archive_incomplete("s")
    _ddl(store, "DROP TRIGGER fail_body")
    result = await archive._write(*args)
    assert result["body"] == {"text": "input"}
    assert await archive._write(*args) == result
    assert not store.archive_incomplete("s")
    assert sum(entry["write_key"] == "key" for entry in store.entries("s")[1]) == 1


async def test_management_write_failure_always_propagates(store):
    _ddl(store, "CREATE TRIGGER fail BEFORE INSERT ON session_entries BEGIN SELECT RAISE(ABORT,'fault'); END")
    with pytest.raises(IntegrityError):
        await commit(store.write, "s", "intent", stage="notify", scope="notification", summary={}, body={"target": "mail"})
    assert len(store.entries("s")[1]) == 1


async def test_expiration_removes_all_historical_bodies_and_keeps_version(store):
    a = write(store, "phase:collect:1")
    b = write(store, "phase:collect:2", "new content")
    store.write("s", "finished", stage="finish", scope="phase", summary={"status": "completed", "execution_epoch": "epoch"})
    store.expire(datetime.now(UTC) + timedelta(days=2))
    view = SessionView(store)
    for version in (a["version"], b["version"]):
        content = await view.get_phase_content("s", "collect", version=version)
        assert content.content is None and content.availability == "expired"
        assert (await view.get_session("s", version=version)).version == version


def test_create_event_failure_rolls_back_header_and_allows_retry(store):
    _ddl(store, "CREATE TRIGGER fail BEFORE INSERT ON session_entries BEGIN SELECT RAISE(ABORT,'fault'); END")
    with pytest.raises(IntegrityError):
        store.create("new", "w", BackupPolicy())
    with store._transaction() as session:
        assert session.get(SessionHeader, "new") is None
    _ddl(store, "DROP TRIGGER fail")
    store.create("new", "w", BackupPolicy())
    assert store.entry("new", "created")["version"] == 1


async def test_memory_database_survives_calls_from_worker_threads():
    store = SessionStore(":memory:")
    try:
        await asyncio.to_thread(store.create, "s", "w", BackupPolicy())
        await asyncio.to_thread(write, store)
        assert store.entry("s", "phase:collect")["version"] == 2
    finally:
        store.close()


@pytest.mark.parametrize("violation", ["foreign_key", "write_key", "version"])
def test_database_constraints_reject_invalid_archive_rows(store, violation):
    original = write(store)
    values = {**original, "summary": "{}", "body": None}
    if violation == "foreign_key":
        values["session_id"] = "absent"
    elif violation == "write_key":
        values["version"] += 1
    else:
        values["write_key"] = "different"
    with pytest.raises(IntegrityError), store._transaction() as session:
        session.add(SessionEntry(**values))
        session.flush()
    assert store.entry("s", "phase:collect") == original


def test_pre_sqlmodel_schema_preserves_data_and_accepts_new_writes(tmp_path):
    import hashlib
    import json

    path = tmp_path / "existing.sqlite3"
    summary = {"status": "created"}
    digest_input = {"stage": None, "scope": "parent", "summary": summary,
                    "body": None, "availability": "available", "category": None}
    digest = hashlib.sha256(json.dumps(digest_input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    engine = create_engine(URL.create("sqlite", database=str(path)))
    try:
        with Session(engine) as session:
            # Freeze the previous schema independently of the new SQLModel metadata.
            session.execute(text("""CREATE TABLE session_headers (
                session_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
                created_at TEXT NOT NULL, policy TEXT NOT NULL)"""))
            session.execute(text("""CREATE TABLE session_entries (
                session_id TEXT NOT NULL REFERENCES session_headers(session_id),
                version INTEGER NOT NULL, write_key TEXT NOT NULL,
                stage TEXT, scope TEXT NOT NULL, summary TEXT NOT NULL,
                body TEXT, availability TEXT NOT NULL, category TEXT, digest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(session_id, version), UNIQUE(session_id, write_key))"""))
            session.execute(text("INSERT INTO session_headers VALUES (:sid,:wid,:at,:policy)"), {
                "sid": "s", "wid": "w", "at": "2026-09-19T00:00:00+00:00",
                "policy": json.dumps(BackupPolicy().model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            })
            session.execute(text("""INSERT INTO session_entries VALUES (
                :sid,1,'created',NULL,'parent',:summary,NULL,'available',NULL,:digest,:at)"""), {
                "sid": "s", "summary": json.dumps(summary), "digest": digest,
                "at": "2026-09-19T00:00:00+00:00",
            })
            session.commit()
    finally:
        engine.dispose()
    store = SessionStore(path)
    try:
        store.create("s", "w", BackupPolicy())
        assert store.entry("s", "created")["summary"] == summary
        first = write(store)
        assert first["version"] == 2
        assert write(store) == first
    finally:
        store.close()
    reopened = SessionStore(path)
    try:
        assert reopened.entry("s", "phase:collect") == first
    finally:
        reopened.close()
