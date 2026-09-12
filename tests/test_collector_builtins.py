"""Built-in collectors preserve file, archive, record and budget boundaries."""

import asyncio
import json
import logging
import os
import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from logagent import archive
from logagent.archive import ArchiveStore
from logagent.collectors import logs
from logagent.collectors.base import CollectionContext
from logagent.collectors.history import HistoryCollector, HistoryOptions
from logagent.collectors.logs import LogsCollector, LogsOptions
from logagent.collectors.manager import CollectorManager
from logagent.collectors.mock import MockCollector, MockOptions
from logagent.collectors.setters import CommonSetters
from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    AnalysisTask,
    BackupPolicy,
    SessionRecord,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)

START = datetime(2026, 9, 1, tzinfo=UTC)


class HistoryReader:
    """An intentionally unordered read-only Archive substitute."""

    def __init__(self, sessions=(), contents=None):
        self.sessions = list(sessions)
        self.contents = contents or {}
        self.calls = []

    async def list(self, *, workflow_id=None, limit=100):
        self.calls.append(("list", workflow_id, limit))
        return deepcopy(self.sessions)

    async def load_artifact(self, session_id, stage):
        self.calls.append(("load", session_id, stage))
        value = self.contents[session_id, stage]
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)


def session(session_id, *, days=0, workflow_id="history", status="completed"):
    instant = START + timedelta(days=days)
    return SessionRecord(
        id=session_id,
        workflow_id=workflow_id,
        status=status,
        created_at=instant,
        updated_at=instant,
        stage="finish",
    )


def final(session_id, *outputs):
    return {
        "outputs": [{"session_id": session_id, "output_id": output_id, "text": text} for output_id, text in outputs],
        "fan_in": None,
    }


def snapshot(workflow_id="history"):
    return WorkflowSnapshot(
        workflow=WorkflowDefinition(
            id=workflow_id, sources=["input"], analyses=[AnalysisTask(id="summary", ai="model")]
        ),
        sources={"input": SourceConfig(id="input", collector="mock")},
        ai={"model": AIConfig(id="model")},
        channels={},
    )


def byte_cost(items):
    text = "\n".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in items)
    return len(text.encode("utf-8"))


async def history_items(reader, *, context=None, **options):
    context = context or CollectionContext(archive=reader)
    items = await HistoryCollector().collect(
        HistoryOptions(workflow_id="history", **options), CommonSetters(), context
    )
    return items, context


async def history_result(reader, *, setters=None, **options):
    return await CollectorManager().collect(
        SourceConfig(id="past", collector="history", options={"workflow_id": "history", **options}, setters=setters or {}),
        CollectionContext(archive=reader),
    )


async def test_mock_declares_ordered_fields_and_returns_detached_unprocessed_data():
    data = [{"level": "info", "text": "一", "nested": {"values": [1]}}, {"other": True, "text": "二"}]
    options = MockOptions(items=data)
    collector = MockCollector()
    assert collector.fields_for(options) == ("level", "text", "nested", "other")
    setters = CommonSetters(fields=["text"], filters=[{"field": "level", "op": "eq", "value": "error"}])
    first = await collector.collect(options, setters, CollectionContext())
    first[0]["nested"]["values"].append(2)
    second = await collector.collect(options, setters, CollectionContext())
    assert second == data
    assert "level" in second[0]  # Filtering and projection belong to Manager.
    assert collector.count(second) == 2


@pytest.mark.parametrize(
    "items", [[{"bad": float("nan")}], [{"bad": float("inf")}], [{1: "bad"}], [{"bad": {1, 2}}], ["not an object"]]
)
def test_mock_rejects_non_json_records(items):
    with pytest.raises(ValidationError):
        MockOptions(items=items)


@pytest.mark.parametrize("field", ["max_bytes", "max_lines"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "4"])
def test_log_limits_are_strict_positive_integers(field, value):
    with pytest.raises(ValidationError):
        LogsOptions(**{field: value})


async def test_logs_select_complete_lines_number_the_fragment_and_handle_rotation(tmp_path):
    path = tmp_path / "tool.log"
    path.write_bytes("first\r\n第二\r\nthird\nunfinished".encode())
    context = CollectionContext(log_path=path)
    collector = LogsCollector()
    assert await collector.collect(LogsOptions(max_lines=2), CommonSetters(), context) == [
        {"line": 1, "text": "第二"},
        {"line": 2, "text": "third"},
    ]
    path.rename(tmp_path / "rotated.log")
    path.write_text("new file\n", encoding="utf-8")
    assert await collector.collect(LogsOptions(), CommonSetters(), context) == [{"line": 1, "text": "new file"}]


async def test_logs_drop_cut_utf8_prefix_and_unterminated_tail(tmp_path):
    path = tmp_path / "tool.log"
    data = "prefix中被截\n完整😀\nlast尾".encode("utf-8")
    path.write_bytes(data)
    # The tail starts at the second byte of 中, never at a decoder boundary.
    options = LogsOptions(max_bytes=len(data) - len(b"prefix") - 1)
    items = await LogsCollector().collect(options, CommonSetters(), CollectionContext(log_path=path))
    assert items == [{"line": 1, "text": "完整😀"}]


@pytest.mark.parametrize("data", [b"", b"unfinished", b"unfinished\xff", b"long line without newline"])
async def test_logs_with_no_complete_line_are_empty(tmp_path, data):
    path = tmp_path / "tool.log"
    path.write_bytes(data)
    assert await LogsCollector().collect(LogsOptions(max_bytes=8), CommonSetters(), CollectionContext(log_path=path)) == []


async def test_logs_bound_reads_keep_aligned_first_line_and_ignore_later_appends(tmp_path, monkeypatch):
    path = tmp_path / "tool.log"
    path.write_bytes(b"x" * 100_000 + b"\nlast\n")
    real_fdopen = logs.os.fdopen
    reads = []
    appended = False

    class ObservedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, count):
            nonlocal appended
            assert count >= 0  # No read-all operation is allowed.
            reads.append(count)
            if count == 5 and not appended:
                with path.open("ab") as writer:
                    writer.write(b"later\n")
                appended = True
            return self.stream.read(count)

    monkeypatch.setattr(logs.os, "fdopen", lambda *args, **kwargs: ObservedStream(real_fdopen(*args, **kwargs)))
    context = CollectionContext(log_path=path)
    assert await LogsCollector().collect(LogsOptions(max_bytes=5), CommonSetters(), context) == [
        {"line": 1, "text": "last"}
    ]
    assert reads == [1, 5]  # One boundary probe and at most max_bytes of content.
    assert await LogsCollector().collect(LogsOptions(max_bytes=6), CommonSetters(), context) == [
        {"line": 1, "text": "later"}
    ]


async def test_logs_missing_unconfigured_and_non_regular_files_are_distinct(tmp_path):
    collector = LogsCollector()
    for path, code, reason in [
        (None, "COLLECTOR_MISSING", "not_configured"),
        (tmp_path / "missing.log", "COLLECTOR_MISSING", "missing"),
        (tmp_path, "COLLECTOR_FAILED", "not_regular_file"),
    ]:
        with pytest.raises(LogAgentError) as caught:
            await collector.collect(LogsOptions(), CommonSetters(), CollectionContext(log_path=path))
        assert caught.value.code == code
        assert caught.value.details["reason"] == reason
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        with pytest.raises(LogAgentError) as caught:
            await asyncio.wait_for(collector.collect(LogsOptions(), CommonSetters(), CollectionContext(log_path=fifo)), 1)
        assert caught.value.details["reason"] == "not_regular_file"


@pytest.mark.parametrize("error", [PermissionError("PRIVATE LOG DATA"), OSError("PRIVATE LOG DATA")])
async def test_log_read_errors_are_safe_failures(tmp_path, monkeypatch, error):
    path = tmp_path / "tool.log"
    path.write_text("private contents\n", encoding="utf-8")
    real_open = logs.os.open

    def fail_open(filename, *args, **kwargs):
        if os.fspath(filename) == os.fspath(path):
            raise error
        return real_open(filename, *args, **kwargs)

    monkeypatch.setattr(logs.os, "open", fail_open)
    result = await CollectorManager().collect(
        SourceConfig(id="logs", collector="logs"), CollectionContext(log_path=path)
    )
    assert result.status == "failed"
    assert result.items == [] and result.text == ""
    assert "PRIVATE" not in json.dumps(result.model_dump(mode="json"))
    assert "private contents" not in result.error.message


async def test_invalid_utf8_in_complete_log_lines_fails(tmp_path):
    path = tmp_path / "tool.log"
    path.write_bytes(b"valid\n\xff\n")
    with pytest.raises(LogAgentError) as caught:
        await LogsCollector().collect(LogsOptions(), CommonSetters(), CollectionContext(log_path=path))
    assert caught.value.code == "COLLECTOR_FAILED"
    assert caught.value.details["reason"] == "invalid_utf8"


@pytest.mark.parametrize("worker_fails", [False, True])
async def test_cancelled_log_read_reaps_its_worker_and_does_not_block_other_sources(tmp_path, monkeypatch, worker_fails):
    path = tmp_path / "tool.log"
    path.write_text("complete\n", encoding="utf-8")
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original_read = logs._read_tail

    def slow_read(*args):
        started.set()
        try:
            if not release.wait(2):
                raise AssertionError("Test did not release the log reader")
            if worker_fails:
                raise OSError("Reader failed after cancellation")
            return original_read(*args)
        finally:
            finished.set()

    monkeypatch.setattr(logs, "_read_tail", slow_read)
    pending = asyncio.create_task(
        LogsCollector().collect(LogsOptions(), CommonSetters(), CollectionContext(log_path=path))
    )
    try:
        assert await asyncio.to_thread(started.wait, 1)
        immediate = await asyncio.wait_for(
            MockCollector().collect(MockOptions(items=[{"text": "ready"}]), CommonSetters(), CollectionContext()), 1
        )
        assert immediate == [{"text": "ready"}]
        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 2)
    assert finished.is_set()
