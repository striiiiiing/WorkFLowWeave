from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime

import pytest

from logagent.models import (
    AIConfig,
    AnalysisTask,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)
from logagent.workflow.__main__ import main
from logagent.workflow.store import SQLiteRunStore


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "runs ?# 中.sqlite3"
    snapshot = WorkflowSnapshot(
        workflow=WorkflowDefinition(
            id="workflow", sources=["source"], analyses=[AnalysisTask(id="analysis", ai="ai")]
        ),
        sources={"source": SourceConfig(id="source", collector="mock")},
        ai={"ai": AIConfig(id="ai", provider="mock", model="mock")},
        channels={},
        created_at=datetime.now(UTC),
    )
    with SQLiteRunStore(path) as store:
        store.create_session("session", snapshot, {"log_path": "input.log"})
        store.append_history("session", "collect", "started", {"input": "logs"})
        store.save_item("session", "collect", "source", {"status": "success", "text": "日志"})
        store.save_stage("session", "collect", {"input": "日志", "count": 1})
        store.append_history("session", "analyze", "started", {"input": "日志"})
        store.save_item("session", "analyze", "analysis", {"status": "success", "text": "分析"})
        store.begin_delivery("session", "output", "channel")
    return path


def test_sessions_command_supports_workflow_filter_and_paging(database, capsys):
    assert main(["--database", str(database), "sessions", "--workflow-id", "workflow"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert [item["session_id"] for item in result] == ["session"]
    assert main(["--database", str(database), "sessions", "--offset", "1"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_show_command_reports_snapshot_stage_results_items_and_uncertain_delivery(database, capsys):
    before = database.read_bytes()
    assert main(["--database", str(database), "show", "session"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["snapshot"]["workflow"]["id"] == "workflow"
    assert result["context"] == {"log_path": "input.log"}
    assert result["stages"] == {"collect": {"input": "日志", "count": 1}}
    assert result["collections"]["source"]["text"] == "日志"
    assert result["analyses"]["analysis"]["text"] == "分析"
    assert result["deliveries"][0]["error"]["code"] == "delivery_uncertain"
    assert database.read_bytes() == before


def test_history_command_reports_ordered_stage_events_with_paging(database, capsys):
    assert (
        main(
            [
                "--database",
                str(database),
                "history",
                "session",
                "--stage",
                "collect",
                "--limit",
                "2",
                "--offset",
                "1",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert [item["event"] for item in result] == ["success", "completed"]
    assert result[0]["payload"]["text"] == "日志"
    assert result[0]["seq"] < result[1]["seq"]


def test_missing_database_errors_as_json_without_creating_files(tmp_path, capsys):
    path = tmp_path / "missing" / "secret-path.sqlite3"
    assert main(["--database", str(path), "sessions"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "storage_failed"
    assert "secret-path" not in captured.err
    assert not path.parent.exists()


@pytest.mark.parametrize(
    "arguments,code",
    [(["show", "missing"], "not_found"), (["sessions", "--limit", "0"], "invalid_argument")],
)
def test_query_failures_are_structured(database, capsys, arguments, code):
    assert main(["--database", str(database), *arguments]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == code


def test_module_entrypoint_runs_in_a_fresh_process(database):
    completed = subprocess.run(
        [sys.executable, "-m", "logagent.workflow", "--database", str(database), "show", "session"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["session_id"] == "session"


def test_show_rejects_deleted_results_instead_of_presenting_incomplete_history(database, capsys):
    with SQLiteRunStore(database) as store:
        store._db.execute("DELETE FROM run_items WHERE stage='collect'")
        store._db.commit()
    assert main(["--database", str(database), "show", "session"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "storage_corrupt"
