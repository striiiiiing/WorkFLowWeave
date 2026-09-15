from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    AnalysisTask,
    DeliveryResult,
    ErrorInfo,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)
from logagent.workflow.store import SQLiteRunStore


@pytest.fixture
def snapshot():
    return WorkflowSnapshot(
        workflow=WorkflowDefinition(
            id="workflow", sources=["source"], analyses=[AnalysisTask(id="analysis", ai="ai")]
        ),
        sources={"source": SourceConfig(id="source", collector="mock")},
        ai={"ai": AIConfig(id="ai", provider="mock", model="mock")},
        channels={},
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def store(tmp_path, snapshot):
    with SQLiteRunStore(tmp_path / "runs.sqlite3") as value:
        value.create_session("session", snapshot, {"log_path": "input.log"})
        yield value


def test_disk_reopen_retains_snapshot_stage_items_and_history(tmp_path, snapshot):
    path = tmp_path / "nested" / "runs.sqlite3"
    with SQLiteRunStore(path) as store:
        store.create_session("session", snapshot, {"log_path": "input.log"})
        store.save_stage("session", "collect", {"input": "logs"}, status="started")
        store.save_item("session", "collect", "source", {"status": "success", "text": "logs"})
        store.save_stage("session", "collect", {"input": "logs", "count": 1})
        store.set_status("session", "interrupted", ErrorInfo(code="interrupted", message="暂停"))
        snapshot.sources["source"].collector = "changed"
    with SQLiteRunStore(path) as store:
        session = store.get_session("session")
        assert session["status"] == "interrupted"
        assert session["stage"] == "collect"
        assert session["snapshot"]["sources"]["source"]["collector"] == "mock"
        assert session["context"] == {"log_path": "input.log"}
        assert session["error"]["code"] == "interrupted"
        assert store.stage_result("session", "collect") == {"input": "logs", "count": 1}
        assert store.item_results("session", "collect") == {
            "source": {"status": "success", "text": "logs"}
        }
        assert [event["event"] for event in store.history("session")] == [
            "created",
            "started",
            "success",
            "completed",
            "interrupted",
        ]


def test_schema_settings_and_native_checkpoint_tables_can_coexist(store):
    db = store._db
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
    assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    assert db.execute("SELECT version FROM run_schema").fetchone()[0] == 1
    db.execute("CREATE TABLE checkpoints (thread_id TEXT, payload BLOB)")
    db.commit()
    store.save_stage("session", "collect", {"value": 1})


def test_duplicate_session_preserves_original_snapshot_and_context(store, snapshot):
    with pytest.raises(LogAgentError) as error:
        store.create_session("session", snapshot, {"different": True})
    assert error.value.code == "session_exists"
    assert store.get_session("session")["context"] == {"log_path": "input.log"}
    assert len(store.history("session")) == 1


def test_json_snapshot_input_and_returned_values_are_isolated(store, snapshot):
    store.create_session("second", snapshot.model_dump(mode="json"), {"nested": {"a": 1}})
    returned = store.get_session("second")
    returned["context"]["nested"]["a"] = 2
    returned["snapshot"]["sources"].clear()
    assert store.get_session("second")["context"] == {"nested": {"a": 1}}
    assert store.get_session("second")["snapshot"]["sources"]


@pytest.mark.parametrize(
    "payload",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {1: "secret"},
        {"value": (1, 2)},
        {"value": object()},
        ["secret"],
    ],
)
def test_non_json_values_rejected_without_partial_writes_or_input_leaks(store, payload):
    with pytest.raises(LogAgentError) as error:
        store.save_stage("session", "collect", payload)
    assert error.value.code == "invalid_argument"
    assert "secret" not in error.value.info.model_dump_json()
    assert store.stage_result("session", "collect") is None
    assert len(store.history("session")) == 1


def test_invalid_snapshot_is_rejected_without_exposing_input(store, snapshot):
    value = snapshot.model_dump(mode="json")
    value["sources"]["source"]["unknown"] = "secret-content"
    with pytest.raises(LogAgentError) as error:
        store.create_session("second", value, {})
    assert error.value.code == "invalid_argument"
    assert "secret-content" not in error.value.info.model_dump_json()
    assert len(store.list_sessions()) == 1


def test_completed_stages_are_idempotent_and_immutable(store):
    store.save_stage("session", "collect", {"value": 1}, status="started")
    assert store.stage_result("session", "collect") is None
    store.save_stage("session", "collect", {"value": 2})
    store.save_stage("session", "collect", {"value": 2})
    assert len(store.history("session", stage="collect")) == 2
    for status in ("completed", "started"):
        with pytest.raises(LogAgentError) as error:
            store.save_stage("session", "collect", {"value": 3}, status=status)
        assert error.value.code == "storage_conflict"
    assert store.stage_result("session", "collect") == {"value": 2}


def test_failed_attempt_history_is_retained_and_success_cannot_be_overwritten(store):
    store.save_item("session", "analyze", "analysis", {"status": "failed", "attempt": 1})
    store.save_item("session", "analyze", "analysis", {"status": "failed", "attempt": 2})
    result = {"status": "success", "text": "analysis"}
    store.save_item("session", "analyze", "analysis", result)
    store.save_item("session", "analyze", "analysis", result)
    with pytest.raises(LogAgentError) as error:
        store.save_item("session", "analyze", "analysis", {"status": "failed"})
    assert error.value.code == "storage_conflict"
    assert store.item_results("session", "analyze") == {"analysis": result}
    assert [event["event"] for event in store.history("session", stage="analyze")] == [
        "failed",
        "failed",
        "success",
    ]


def fail_history_inserts(store):
    store._db.execute(
        "CREATE TRIGGER history_failure BEFORE INSERT ON run_history "
        "BEGIN SELECT RAISE(ABORT, 'secret-database-error'); END"
    )
    store._db.commit()


def test_stage_and_session_update_roll_back_when_history_write_fails(store):
    fail_history_inserts(store)
    with pytest.raises(LogAgentError) as error:
        store.save_stage("session", "collect", {"value": "secret-content"})
    assert error.value.code == "storage_failed"
    assert "secret" not in error.value.info.model_dump_json()
    assert store.stage_result("session", "collect") is None
    assert store.get_session("session")["stage"] == "created"
    assert len(store.history("session")) == 1


def test_stage_progress_updates_session_atomically_with_history(store):
    store.append_history("session", "analyze", "started", {"input": "logs"})
    assert store.get_session("session")["stage"] == "analyze"
    assert store.history("session", stage="analyze")[0]["payload"] == {"input": "logs"}
    fail_history_inserts(store)
    with pytest.raises(LogAgentError):
        store.append_history("session", "aggregate", "started", {"input": "analysis"})
    assert store.get_session("session")["stage"] == "analyze"
    assert store.history("session", stage="aggregate") == []


def test_create_and_status_are_atomic_with_history(store, snapshot):
    fail_history_inserts(store)
    with pytest.raises(LogAgentError):
        store.create_session("second", snapshot, {})
    assert [item["session_id"] for item in store.list_sessions()] == ["session"]
    with pytest.raises(LogAgentError):
        store.set_status("session", "failed", ErrorInfo(code="failed", message="Failure"))
    assert store.get_session("session")["status"] == "running"
    assert store.get_session("session")["error"] is None


def test_item_and_delivery_intent_are_atomic_with_history(store):
    fail_history_inserts(store)
    with pytest.raises(LogAgentError):
        store.save_item("session", "collect", "source", {"status": "success"})
    with pytest.raises(LogAgentError):
        store.begin_delivery("session", "output", "channel")
    assert store.item_results("session", "collect") == {}
    assert store.delivery_results("session") == []


@pytest.mark.parametrize("operation", ["stage", "item", "intent", "status", "history", "read"])
def test_missing_sessions_cannot_create_orphan_rows(store, operation):
    calls = {
        "stage": lambda: store.save_stage("missing", "collect", {}),
        "item": lambda: store.save_item("missing", "collect", "source", {}),
        "intent": lambda: store.begin_delivery("missing", "output", "channel"),
        "status": lambda: store.set_status("missing", "failed"),
        "history": lambda: store.history("missing"),
        "read": lambda: store.get_session("missing"),
    }
    with pytest.raises(LogAgentError) as error:
        calls[operation]()
    assert error.value.code == "not_found"
    assert store._db.execute("SELECT COUNT(*) FROM run_history").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        store._db.execute("INSERT INTO run_items VALUES('missing','collect','x','failed','{}','x')")
    store._db.rollback()


def test_pending_delivery_survives_reopen_and_blocks_repeated_send(tmp_path, snapshot):
    path = tmp_path / "runs.sqlite3"
    with SQLiteRunStore(path) as store:
        store.create_session("session", snapshot, {})
        assert store.begin_delivery("session", "output", "channel") is True
    with SQLiteRunStore(path) as store:
        assert store.begin_delivery("session", "output", "channel") is False
        pending = store.delivery_results("session")
        assert pending[0]["status"] == "failed"
        assert pending[0]["error"]["code"] == "delivery_uncertain"
        assert pending[0]["attempts"] == 1
        assert store.item_results("session", "notify")["output:channel"]["status"] == "sending"
        with pytest.raises(LogAgentError):
            store.save_item("session", "notify", "output:channel", {"status": "success"})


def test_delivery_receipt_is_immutable_and_retains_send_intent_history(store):
    result = DeliveryResult(channel_id="channel", output_id="output", status="success", attempts=1)
    with pytest.raises(LogAgentError) as error:
        store.save_delivery("session", result)
    assert error.value.code == "storage_conflict"
    assert store.begin_delivery("session", "output", "channel")
    store.save_delivery("session", result)
    store.save_delivery("session", result)
    assert store.begin_delivery("session", "output", "channel") is False
    assert store.delivery_results("session") == [result.model_dump(mode="json")]
    with pytest.raises(LogAgentError):
        store.save_delivery("session", result.model_copy(update={"status": "timeout"}))
    assert [row["event"] for row in store.history("session", stage="notify")] == [
        "sending",
        "success",
    ]


def test_failed_receipt_is_not_resent(store):
    assert store.begin_delivery("session", "output", "channel")
    store.save_delivery(
        "session",
        {
            "channel_id": "channel",
            "output_id": "output",
            "status": "failed",
            "attempts": 1,
            "error": {"code": "failed", "message": "Failed", "details": {}},
        },
    )
    assert store.begin_delivery("session", "output", "channel") is False
    assert store.delivery_results("session")[0]["error"]["code"] == "failed"


def test_receipt_history_failure_keeps_uncertain_intent(store):
    store.begin_delivery("session", "output", "channel")
    fail_history_inserts(store)
    with pytest.raises(LogAgentError):
        store.save_delivery(
            "session",
            {
                "channel_id": "channel",
                "output_id": "output",
                "status": "success",
                "attempts": 1,
            },
        )
    assert store.delivery_results("session")[0]["error"]["code"] == "delivery_uncertain"


def test_paging_and_stage_and_workflow_filters(store, snapshot):
    for index in range(4):
        store.create_session(f"session_{index}", snapshot, {})
        store.save_item("session", "collect", f"item_{index}", {"status": "failed", "index": index})
    rows = store.list_sessions(limit=2)
    assert len(rows) == 2
    assert store.list_sessions(limit=2, offset=2)[0] != rows[0]
    assert len(store.list_sessions(workflow_id="workflow")) == 5
    assert store.list_sessions(workflow_id="other") == []
    history = store.history("session", stage="collect", limit=2, offset=1)
    assert [event["payload"]["index"] for event in history] == [1, 2]
    assert history[0]["seq"] < history[1]["seq"]


@pytest.mark.parametrize("limit,offset", [(0, 0), (1001, 0), (True, 0), (1, -1), (1, True)])
def test_invalid_pagination_is_rejected(store, limit, offset):
    for call in (store.list_sessions, lambda **kwargs: store.history("session", **kwargs)):
        with pytest.raises(LogAgentError) as error:
            call(limit=limit, offset=offset)
        assert error.value.code == "invalid_argument"


@pytest.mark.parametrize("kind", ["snapshot", "context", "error", "stage", "item", "history"])
def test_corrupt_hashes_are_rejected_without_exposing_payload(store, kind):
    if kind in {"snapshot", "context", "error"}:
        store._db.execute(f"UPDATE run_sessions SET {kind}_json=?", ('{"secret-content": true}',))

        def read():
            return store.get_session("session")
    else:
        store.save_stage("session", "collect", {"input": "logs"})
        store.save_item("session", "collect", "source", {"status": "success"})
        table = {"stage": "run_stages", "item": "run_items", "history": "run_history"}[kind]
        store._db.execute(f"UPDATE {table} SET payload_json=?", ('{"secret-content": true}',))
        read = {
            "stage": lambda: store.stage_result("session", "collect"),
            "item": lambda: store.item_results("session", "collect"),
            "history": lambda: store.history("session"),
        }[kind]
    store._db.commit()
    with pytest.raises(LogAgentError) as error:
        read()
    assert error.value.code == "storage_corrupt"
    assert "secret-content" not in error.value.info.model_dump_json()


def test_checksum_does_not_replace_snapshot_schema_validation(store):
    payload = json.dumps({"secret-content": True})
    digest = hashlib.sha256(payload.encode()).hexdigest()
    store._db.execute("UPDATE run_sessions SET snapshot_json=?,snapshot_hash=?", (payload, digest))
    store._db.commit()
    with pytest.raises(LogAgentError) as error:
        store.get_session("session")
    assert error.value.code == "storage_corrupt"
    assert "secret-content" not in error.value.info.model_dump_json()


def test_unsupported_schema_and_corrupt_file_have_structured_errors(tmp_path):
    path = tmp_path / "runs.sqlite3"
    with SQLiteRunStore(path):
        pass
    with sqlite3.connect(path) as db:
        db.execute("UPDATE run_schema SET version=999")
    with pytest.raises(LogAgentError) as error:
        SQLiteRunStore(path)
    assert error.value.code == "storage_version"
    broken = tmp_path / "secret-path.sqlite3"
    broken.write_text("secret-content")
    with pytest.raises(LogAgentError) as error:
        SQLiteRunStore(broken)
    assert error.value.code == "storage_failed"
    assert "secret" not in error.value.info.model_dump_json()


def test_claims_cover_multiple_instances_and_release_on_close(tmp_path, snapshot):
    path = tmp_path / "runs.sqlite3"
    first = SQLiteRunStore(path)
    second = SQLiteRunStore(path)
    try:
        first.create_session("session", snapshot, {})
        assert first.claim("session") is True
        assert first.claim("session") is False
        assert second.claim("session") is False
        second.release("session")
        assert second.claim("session") is False
        first.release("session")
        assert second.claim("session") is True
        second.close()
        assert first.claim("session") is True
    finally:
        first.close()
        second.close()


def test_memory_instances_are_independent_and_close_is_idempotent(snapshot):
    first = SQLiteRunStore(":memory:")
    second = SQLiteRunStore(":memory:")
    try:
        first.create_session("session", snapshot, {})
        assert second.list_sessions() == []
        assert first.claim("session") is True
        assert second.claim("session") is True
    finally:
        first.close()
        second.close()
    first.close()
    with pytest.raises(LogAgentError) as error:
        first.list_sessions()
    assert error.value.code == "storage_closed"


def test_read_only_connections_query_without_changing_database(tmp_path, snapshot):
    path = tmp_path / "runs.sqlite3"
    with SQLiteRunStore(path) as writer:
        writer.create_session("session", snapshot, {})
        writer.save_stage("session", "collect", {"input": "logs"})
    before = path.read_bytes()
    with SQLiteRunStore(path, read_only=True) as reader:
        assert reader.get_session("session")["stage"] == "collect"
        assert reader.stage_result("session", "collect") == {"input": "logs"}
        assert len(reader.history("session")) == 2
        with pytest.raises(LogAgentError) as error:
            reader.set_status("session", "failed")
        assert error.value.code == "storage_readonly"
        with pytest.raises(sqlite3.OperationalError):
            reader._db.execute("DELETE FROM run_history")
    assert path.read_bytes() == before


def test_read_only_open_does_not_create_missing_database_or_folders(tmp_path):
    path = tmp_path / "missing" / "runs.sqlite3"
    with pytest.raises(LogAgentError) as error:
        SQLiteRunStore(path, read_only=True)
    assert error.value.code == "storage_failed"
    assert not path.parent.exists()
    with pytest.raises(LogAgentError) as error:
        SQLiteRunStore(":memory:", read_only=True)
    assert error.value.code == "invalid_argument"


def record_verified_run(store):
    store.append_history("session", "collect", "started", {"input": "logs"})
    store.save_item("session", "collect", "source", {"status": "failed", "attempt": 1})
    store.save_item("session", "collect", "source", {"status": "success", "text": "logs"})
    store.save_stage(
        "session",
        "collect",
        {
            "session_id": "session",
            "stage": "collect",
            "text": "logs",
        },
    )
    store.begin_delivery("session", "output", "channel")
    store.save_stage(
        "session",
        "finish",
        {
            "session_id": "session",
            "stage": "finish",
            "status": "completed",
        },
    )
    store.set_status("session", "completed")


def test_verify_session_handles_multiple_completed_events_and_pending_intents(store):
    record_verified_run(store)
    store.verify_session("session")
    with SQLiteRunStore(store.location, read_only=True) as reader:
        reader.verify_session("session")


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM run_stages WHERE stage='collect'",
        "DELETE FROM run_items WHERE stage='collect'",
        "DELETE FROM run_items WHERE stage='notify'",
        "DELETE FROM run_history WHERE stage='collect' AND event='success'",
        "DELETE FROM run_history WHERE stage='collect' AND event='completed'",
        "DELETE FROM run_history WHERE event='sending'",
        "DELETE FROM run_history WHERE event='created'",
        "UPDATE run_items SET status='failed' WHERE stage='collect'",
        "UPDATE run_history SET event='failed' WHERE stage='collect' AND event='success'",
        "UPDATE run_stages SET status='started' WHERE stage='collect'",
        "UPDATE run_sessions SET workflow_id='different'",
    ],
)
def test_verify_session_rejects_missing_or_inconsistent_committed_facts(store, statement):
    record_verified_run(store)
    store._db.execute(statement)
    store._db.commit()
    with pytest.raises(LogAgentError) as error:
        store.verify_session("session")
    assert error.value.code == "storage_corrupt"
    assert store._db.in_transaction is False


@pytest.mark.parametrize(
    "table,column",
    [
        ("run_sessions", "snapshot_json"),
        ("run_sessions", "context_json"),
        ("run_sessions", "error_json"),
        ("run_stages", "payload_json"),
        ("run_items", "payload_json"),
        ("run_history", "payload_json"),
    ],
)
def test_verify_session_checks_every_json_payload(store, table, column):
    record_verified_run(store)
    store._db.execute(f"UPDATE {table} SET {column}=?", ('{"secret-content":true}',))
    store._db.commit()
    with pytest.raises(LogAgentError) as error:
        store.verify_session("session")
    assert error.value.code == "storage_corrupt"
    assert "secret-content" not in error.value.info.model_dump_json()


def test_verify_session_reads_all_facts_inside_one_database_transaction(store):
    record_verified_run(store)
    statements = []
    store._db.set_trace_callback(statements.append)
    store.verify_session("session")
    store._db.set_trace_callback(None)
    assert statements[0] == "BEGIN"
    assert statements[-1] == "COMMIT"
    assert sum(statement.startswith("SELECT") for statement in statements) == 4


def test_verify_session_rejects_individually_valid_payload_with_inconsistent_history(store):
    record_verified_run(store)
    payload = json.dumps({"status": "success", "text": "changed"})
    digest = hashlib.sha256(payload.encode()).hexdigest()
    store._db.execute(
        "UPDATE run_items SET payload_json=?,payload_hash=? WHERE stage='collect'",
        (payload, digest),
    )
    store._db.commit()
    with pytest.raises(LogAgentError) as error:
        store.verify_session("session")
    assert error.value.code == "storage_corrupt"


def test_verify_session_rejects_completed_stage_identity_mismatch(store):
    record_verified_run(store)
    payload = json.dumps({"session_id": "other", "stage": "collect"})
    digest = hashlib.sha256(payload.encode()).hexdigest()
    store._db.execute(
        "UPDATE run_history SET payload_json=?,payload_hash=? "
        "WHERE stage='collect' AND event='completed'",
        (payload, digest),
    )
    store._db.commit()
    with pytest.raises(LogAgentError) as error:
        store.verify_session("session")
    assert error.value.code == "storage_corrupt"


def test_verify_session_uses_consistent_snapshot_while_another_connection_commits(store):
    record_verified_run(store)
    with SQLiteRunStore(store.location) as writer:

        def interleave_write(statement):
            if statement.startswith("SELECT * FROM run_history"):
                writer.save_item(
                    "session", "analyze", "later", {"status": "success", "text": "new"}
                )

        store._db.set_trace_callback(interleave_write)
        store.verify_session("session")
        store._db.set_trace_callback(None)
    assert store.item_results("session", "analyze")["later"]["text"] == "new"
    store.verify_session("session")


def test_concurrent_thread_writes_keep_fact_and_history_transactions_together(store):
    def write(index):
        store.save_item(
            "session", "collect", f"source_{index}", {"status": "success", "index": index}
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(30)))
    assert len(store.item_results("session", "collect")) == 30
    assert len(store.history("session", stage="collect")) == 30
    store.verify_session("session")


def test_default_database_is_persistent_and_invalid_paths_do_not_make_temporary_databases(
    tmp_path, monkeypatch, snapshot
):
    monkeypatch.chdir(tmp_path)
    with SQLiteRunStore() as store:
        store.create_session("session", snapshot, {})
    path = tmp_path / "data" / "workflows.sqlite3"
    assert path.is_file()
    with SQLiteRunStore() as store:
        assert store.get_session("session")["workflow_id"] == "workflow"
    for location in ("", "\x00"):
        with pytest.raises(LogAgentError) as error:
            SQLiteRunStore(location)
        assert error.value.code == "invalid_argument"
