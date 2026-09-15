"""Recovery must survive abrupt interpreter exits, including unflushed graph state."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from logagent.workflow import SQLiteRunStore

_CHILD_PROGRAM = """
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from logagent.models import (
    AIConfig, AnalysisResult, AnalysisTask, ChannelConfig, CollectionResult,
    DeliveryResult, SourceConfig, WorkflowDefinition, WorkflowSnapshot,
)
from logagent.workflow import SQLiteRunStore, WorkflowService

database, ledger_path, report_path, mode = sys.argv[1:]

if mode == "crash-notify":
    original_put = AsyncSqliteSaver.aput

    async def hold_aggregate_checkpoint(self, config, checkpoint, metadata, new_versions):
        if checkpoint["channel_values"].get("result", {}).get("stage") == "aggregate":
            # Keep the completed aggregate in pending_writes when the process
            # exits. aget_state then has next=() but a completed pending task.
            await asyncio.Future()
        return await original_put(self, config, checkpoint, metadata, new_versions)

    AsyncSqliteSaver.aput = hold_aggregate_checkpoint


def record(kind, **details):
    # This ledger stands in for an external provider's durable side effect.
    with open(ledger_path, "a", encoding="utf-8") as ledger:
        ledger.write(json.dumps({"kind": kind, **details}) + "\\n")
        ledger.flush()
        os.fsync(ledger.fileno())


class Store(SQLiteRunStore):
    def save_delivery(self, session_id, receipt):
        if mode == "crash-notify" and receipt["channel_id"] == "one":
            # The provider returned success, but no receipt is committed.
            os._exit(74)
        return super().save_delivery(session_id, receipt)


store = Store(database)


class Collector:
    async def collect(self, config, context):
        record("collect", source_id=config.id)
        return CollectionResult(
            source_id=config.id, status="success", text="durable input", count=1
        )


class AI:
    async def execute(self, config, prompt, text, *, task_id, context):
        record("analyze", task_id=task_id, text=text, model=config.model)
        if mode == "crash-analysis" and task_id == "second":
            assert store.stage_result("run", "collect")["shared_input"] == "durable input"
            assert store.item_results("run", "analyze")["first"]["status"] == "success"
            # No cancellation, shutdown, connection close, or finally handlers.
            os._exit(73)
        return AnalysisResult(task_id=task_id, status="success", text=f"{task_id}({text})")


class Channel:
    async def send(self, config, notification):
        record("send", output_id=notification.output_id, channel_id=config.id)
        return DeliveryResult(
            channel_id=config.id, output_id=notification.output_id,
            status="success", attempts=1,
        )


async def main():
    service = WorkflowService(Collector(), AI(), Channel(), run_store=store)
    if mode == "recover":
        result = await service.recover("run")
    else:
        notification_crash = mode == "crash-notify"
        tasks = ("first",) if notification_crash else ("first", "second")
        channels = ["one", "two"] if notification_crash else []
        snapshot = WorkflowSnapshot(
            workflow=WorkflowDefinition(
                id="demo", sources=["source"],
                analyses=[AnalysisTask(id=key, ai="ai", prompt="{input}") for key in tasks],
                channels=channels, analysis_concurrency=1,
            ),
            sources={"source": SourceConfig(id="source", collector="mock")},
            ai={"ai": AIConfig(id="ai", provider="mock", model="original-model")},
            channels={key: ChannelConfig(id=key, channel="mock") for key in channels},
            created_at=datetime.now(UTC),
        )
        result = await service.trigger(snapshot, session_id="run")
    report = {
        "result": result.model_dump(mode="json"),
        "history": await service.history("run", limit=1000),
        "session": await service.get_session("run"),
    }
    Path(report_path).write_text(json.dumps(report), encoding="utf-8")
    await service.shutdown()
    store.close()


asyncio.run(main())
"""


def _run_child(tmp_path, mode, expected_returncode):
    program = tmp_path / "workflow_child.py"
    program.write_text(_CHILD_PROGRAM, encoding="utf-8")
    environment = os.environ.copy()
    source = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (source, environment.get("PYTHONPATH")))
    )
    # subprocess.run kills and reaps the child if its bounded wait expires.
    completed = subprocess.run(
        [
            sys.executable,
            str(program),
            str(tmp_path / "runs.sqlite3"),
            str(tmp_path / "provider.jsonl"),
            str(tmp_path / "report.json"),
            mode,
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == expected_returncode, completed.stdout + completed.stderr


def _ledger(tmp_path):
    return [
        json.loads(line)
        for line in (tmp_path / "provider.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def _report(tmp_path):
    return json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))


def test_hard_exit_during_analysis_recovers_only_unfinished_branch(tmp_path):
    _run_child(tmp_path, "crash-analysis", 73)
    database = tmp_path / "runs.sqlite3"
    with SQLiteRunStore(database) as store:
        assert store.stage_result("run", "collect")["shared_input"] == "durable input"
        assert store.stage_result("run", "analyze") is None
        assert list(store.item_results("run", "analyze")) == ["first"]
    with sqlite3.connect(database) as db:
        assert (
            db.execute("SELECT count(*) FROM checkpoints WHERE thread_id=?", ("run",)).fetchone()[0]
            > 0
        )

    _run_child(tmp_path, "recover", 0)
    events = _ledger(tmp_path)
    assert [event["kind"] for event in events] == ["collect", "analyze", "analyze", "analyze"]
    assert [event["task_id"] for event in events if event["kind"] == "analyze"] == [
        "first",
        "second",
        "second",
    ]
    assert events[-1]["text"] == "durable input"
    assert events[-1]["model"] == "original-model"
    report = _report(tmp_path)
    assert report["result"]["status"] == "completed"
    assert [item["text"] for item in report["result"]["analyses"]] == [
        "first(durable input)",
        "second(durable input)",
    ]
    assert [
        event["stage"]
        for event in report["history"]
        if event["event"] == "completed" and "session_id" in event["payload"]
    ] == [
        "collect",
        "analyze",
        "aggregate",
        "notify",
        "finish",
    ]
    assert any(event["event"] == "resumed" for event in report["history"])

    # A third interpreter reading the completed session also performs no I/O.
    _run_child(tmp_path, "recover", 0)
    assert _ledger(tmp_path) == events


def test_hard_exit_after_send_preserves_uncertainty_and_continues_next_target(tmp_path):
    _run_child(tmp_path, "crash-notify", 74)
    with SQLiteRunStore(tmp_path / "runs.sqlite3") as store:
        assert store.stage_result("run", "aggregate") is not None
        assert store.stage_result("run", "notify") is None
        assert store.item_results("run", "notify")["first:one"]["status"] == "sending"
    assert [event for event in _ledger(tmp_path) if event["kind"] == "send"] == [
        {"kind": "send", "output_id": "first", "channel_id": "one"}
    ]

    _run_child(tmp_path, "recover", 0)
    events = _ledger(tmp_path)
    assert [event["kind"] for event in events] == ["collect", "analyze", "send", "send"]
    assert [event["channel_id"] for event in events if event["kind"] == "send"] == ["one", "two"]
    report = _report(tmp_path)
    assert report["result"]["status"] == "partial"
    first, second = report["result"]["deliveries"]
    assert first["channel_id"] == "one"
    assert first["error"]["code"] == "delivery_uncertain"
    assert first["error"]["details"]["delivery_uncertain"] is True
    assert second["channel_id"] == "two" and second["status"] == "success"
    notify_history = [event for event in report["history"] if event["stage"] == "notify"]
    assert any(
        event["event"] == "completed"
        and event["payload"]["deliveries"][0]["error"]["code"] == "delivery_uncertain"
        for event in notify_history
    )

    # Uncertain deliveries remain final even after another process restart.
    _run_child(tmp_path, "recover", 0)
    assert _ledger(tmp_path) == events
    assert _report(tmp_path)["result"] == report["result"]
