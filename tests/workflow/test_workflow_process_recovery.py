"""Workflow 进程强退后的持久恢复测试。

启动真实 Python 子进程并在分析、发送或业务提交后强退，再重建服务恢复；
通过存档、checkpoint 和调用记录断言只补未完成分支，已完成采集不重复，
发送确认窗口保留不确定性。外部业务组件为子进程内替身，数据库在临时目录。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from logagent.workflow import SessionStore
from tests.workflow.helpers import archived

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
from logagent.workflow import SessionStore, WorkflowService
from tests.workflow.helpers import archived
import threading
receipt_committed = threading.Event()

database, ledger_path, report_path, mode = sys.argv[1:]



def record(kind, **details):
    # This ledger stands in for an external provider's durable side effect.
    with open(ledger_path, "a", encoding="utf-8") as ledger:
        ledger.write(json.dumps({"kind": kind, **details}) + "\\n")
        ledger.flush()
        os.fsync(ledger.fileno())


class Store(SessionStore):
    def write(self, sid, key, **kwargs):
        if mode == "crash-notify" and key.startswith("delivery:first:one:epoch:"):
            assert receipt_committed.wait(5)
            os._exit(74)
        result = super().write(sid, key, **kwargs)
        if key.startswith("delivery:first:two:epoch:"):
            receipt_committed.set()
        if mode == "crash-archive" and key.startswith("collect:item:source:epoch:"):
            os._exit(75)
        return result


store = Store(database)


class Collector:
    async def collect(self, config, context):
        record("collect", source_id=config.id)
        return CollectionResult(
            source_id=config.id, status="success", text="durable input", count=1
        )


class AI:
    async def execute(self, config, prompt, text, *, model, task_id, context,
                      system_prompt=None, user_prompt=""):
        record("analyze", task_id=task_id, text=text, model=model)
        if mode in {"crash-analysis", "rerun-crash"} and task_id == "second":
            assert (await asyncio.to_thread(archived, store, "run", "phase:collect"))["body"]["shared_input"] == "durable input\\n\\nsource: success (1)"
            assert (await asyncio.to_thread(archived, store, "run", "analyze:item:first"))["body"]["status"] == "success"
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
    service = WorkflowService(Collector(), AI(), Channel(), session_store=store)
    await service.start()
    used_namespaces = []
    put = service._checkpointer.aput
    async def tracking_put(config, checkpoint, metadata, new_versions):
        used_namespaces.append(config["configurable"].get("checkpoint_ns", ""))
        return await put(config, checkpoint, metadata, new_versions)
    service._checkpointer.aput = tracking_put
    if mode in {"recover", "rerun-crash"}:
        await service.resume("run", stage="analyze" if mode == "rerun-crash" else None)
        result = await service.wait("run")
    else:
        notification_crash = mode == "crash-notify"
        tasks = ("first",) if notification_crash else ("first", "second")
        channels = ["one", "two"] if notification_crash else []
        snapshot = WorkflowSnapshot(
            workflow=WorkflowDefinition(
                id="demo", sources=["source"],
                analyses=[AnalysisTask(id=key, ai="ai", model="original-model") for key in tasks],
                channels=channels, analysis_concurrency=1,
            ),
            sources={"source": SourceConfig(id="source", collector="mock")},
            ai={"ai": AIConfig(id="ai", provider="mock", models={"original-model": {}})},
            channels={key: ChannelConfig(id=key, channel="mock") for key in channels},
            created_at=datetime.now(UTC),
        )
        await service.trigger(snapshot, session_id="run")
        result = await service.wait("run")
    report = {
        "used_namespaces": used_namespaces,
        "result": result.model_dump(mode="json"),
        "history": await service.history("run"),
        "session": (await service.get_session("run")).model_dump(mode="json"),
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
    source = str(Path(__file__).resolve().parents[2] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (source, str(Path(source).parent), environment.get("PYTHONPATH")))
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
    store = SessionStore(database)
    try:
        assert archived(store, "run", "phase:collect")["body"]["shared_input"] == "durable input\n\nsource: success (1)"
        assert archived(store, "run", "phase:analyze") is None
        assert archived(store, "run", "analyze:item:first") is not None
    finally:
        store.close()
    with SqliteSaver.from_conn_string(str(database)) as saver:
        original = saver.get_tuple({"configurable": {"thread_id": "run"}})
        epoch = original.checkpoint["channel_values"]["execution_epoch"]
        active_namespaces = {cp.config["configurable"]["checkpoint_ns"] for cp in saver.list(None)
                             if cp.config["configurable"]["checkpoint_ns"].startswith("analyze:")}

    _run_child(tmp_path, "recover", 0)
    events = _ledger(tmp_path)
    assert [event["kind"] for event in events] == ["collect", "analyze", "analyze", "analyze"]
    assert [event["task_id"] for event in events if event["kind"] == "analyze"] == [
        "first",
        "second",
        "second",
    ]
    assert events[-1]["text"] == "durable input\n\nsource: success (1)"
    assert events[-1]["model"] == "original-model"
    report = _report(tmp_path)
    assert active_namespaces <= set(report["used_namespaces"])
    assert report["session"]["execution_epoch"] == epoch
    assert report["result"]["status"] == "completed"
    assert [item["text"] for item in report["result"]["analyses"]] == [
        "first(durable input\n\nsource: success (1))",
        "second(durable input\n\nsource: success (1))",
    ]
    assert [event["stage"] for event in report["history"] if event["scope"] == "phase"] == [
        "collect",
        "analyze",
        "aggregate",
        "notify",
        "finish",
    ]
    assert any(event["write_key"].startswith("running:") for event in report["history"])

    # A third interpreter reading the completed session also performs no I/O.
    _run_child(tmp_path, "recover", 0)
    assert _ledger(tmp_path) == events


def test_hard_exit_after_send_preserves_uncertainty_and_continues_next_target(tmp_path):
    _run_child(tmp_path, "crash-notify", 74)
    store = SessionStore(tmp_path / "runs.sqlite3")
    try:
        assert archived(store, "run", "phase:aggregate") is not None
        assert archived(store, "run", "phase:notify") is None
        assert archived(store, "run", "intent:first:one") is not None
        assert archived(store, "run", "delivery:first:one") is None
    finally:
        store.close()
    assert {event["channel_id"] for event in _ledger(tmp_path) if event["kind"] == "send"} == {"one", "two"}

    _run_child(tmp_path, "recover", 0)
    events = _ledger(tmp_path)
    assert [event["kind"] for event in events] == ["collect", "analyze", "send", "send"]
    assert sorted(event["channel_id"] for event in events if event["kind"] == "send") == ["one", "two"]
    report = _report(tmp_path)
    assert report["result"]["status"] == "partial"
    first, second = report["result"]["deliveries"]
    assert first["channel_id"] == "one"
    assert first["error"]["code"] == "delivery_uncertain"
    assert first["error"]["details"]["delivery_uncertain"] is True
    assert second["channel_id"] == "two" and second["status"] == "success"
    notify_history = [event for event in report["history"] if event["stage"] == "notify"]
    assert any(
        event["scope"] == "phase"
        and event["body"]["deliveries"][0]["error"]["code"] == "delivery_uncertain"
        for event in notify_history
    )

    # Uncertain deliveries remain final even after another process restart.
    _run_child(tmp_path, "recover", 0)
    assert _ledger(tmp_path) == events
    assert _report(tmp_path)["result"] == report["result"]


def test_hard_exit_after_business_commit_before_checkpoint_reuses_collector(tmp_path):
    _run_child(tmp_path, "crash-archive", 75)
    assert [event["kind"] for event in _ledger(tmp_path)] == ["collect"]
    _run_child(tmp_path, "recover", 0)
    events = _ledger(tmp_path)
    assert [event["kind"] for event in events] == ["collect", "analyze", "analyze"]
    assert _report(tmp_path)["result"]["status"] == "completed"


def test_hard_exit_in_new_execution_epoch_resumes_that_round(tmp_path):
    _run_child(tmp_path, "complete", 0)
    first_epoch = _report(tmp_path)["session"]["execution_epoch"]
    _run_child(tmp_path, "rerun-crash", 73)
    with SqliteSaver.from_conn_string(str(tmp_path / "runs.sqlite3")) as saver:
        saved = saver.get_tuple({"configurable": {"thread_id": "run"}})
        second_epoch = saved.checkpoint["channel_values"]["execution_epoch"]
    assert first_epoch != second_epoch
    _run_child(tmp_path, "recover", 0)
    assert _report(tmp_path)["session"]["execution_epoch"] == second_epoch
    events = _ledger(tmp_path)
    assert sum(event["kind"] == "collect" for event in events) == 1
    assert sum(event.get("task_id") == "first" for event in events) == 2
    assert sum(event.get("task_id") == "second" for event in events) == 3
