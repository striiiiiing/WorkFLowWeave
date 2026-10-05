"""日志采集器的有界文件读取测试。

以临时日志文件和实际采集器验证路径、格式、筛选及读取边界；注入读失败、
文件变化和取消，断言异常不伪装成功，描述符最终关闭，错误不泄露敏感数据。
并发调用核对各自路径及结果隔离，不读取应用真实日志。
"""

import asyncio
import json
import os
from pathlib import Path
from threading import Event

import pytest

from logagent.errors import LogAgentError
from logagent.models import CollectionContext
from logagent.schema import validate_schema
from plugins.logs import collector as logs
from plugins.logs.collector import LogsCollector


def context(path: Path | str | None) -> CollectionContext:
    return CollectionContext(
        workflow_id="workflow", session_id="current", log_path=None if path is None else str(path)
    )


def line(record: dict) -> bytes:
    return (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")


@pytest.fixture
def collector():
    return LogsCollector()


def test_schemas_describe_every_public_setting(collector):
    for schema in (collector.options_schema, collector.setters_schema):
        validate_schema(schema)
        assert schema["additionalProperties"] is False
        assert all(
            rule.get("description") and rule.get("type") for rule in schema["properties"].values()
        )
    assert set(collector.options_schema["properties"]) == {"max_lines", "max_bytes"}
    assert set(collector.setters_schema["properties"]) == {
        "levels",
        "modules",
        "session_id",
        "start_time",
        "end_time",
        "fields",
        "group_by",
    }
    assert collector.options_schema["properties"]["max_lines"]["default"] == 200
    assert collector.options_schema["properties"]["max_bytes"]["default"] == 256 * 1024


@pytest.mark.parametrize(
    ("options", "setters"),
    [
        ({"max_lines": 0}, {}),
        ({"max_lines": 10_001}, {}),
        ({"max_lines": True}, {}),
        ({"max_lines": 2.0}, {}),
        ({"max_bytes": 0}, {}),
        ({"max_bytes": 16 * 1024 * 1024 + 1}, {}),
        ({"max_bytes": "100"}, {}),
        ({"path": "/secret/override"}, {}),
        ({}, {"unknown": "secret"}),
        ({}, {"levels": "INFO"}),
        ({}, {"modules": [""]}),
        ({}, {"fields": ["secret"]}),
        ({}, {"fields": ["time", "time"]}),
        ({}, {"group_by": "secret"}),
        ({}, {"session_id": "session\n"}),
        ({}, {"start_time": "2026-09-13T00:00:00"}),
        ({}, {"start_time": "2026-09-13"}),
        ({}, {"end_time": "invalid"}),
        ({}, {"start_time": "2026-09-14T00:00:00Z", "end_time": "2026-09-13T00:00:00Z"}),
    ],
)
async def test_invalid_configuration_rejected_before_io(collector, monkeypatch, options, setters):
    def unexpected_stat(*args, **kwargs):
        raise AssertionError("validation must not access a file")

    monkeypatch.setattr(logs.os, "stat", unexpected_stat)
    with pytest.raises(LogAgentError) as caught:
        await collector.collect(options, setters, context("/unused"))
    assert caught.value.code == "invalid_config"
    assert "secret" not in caught.value.info.model_dump_json()


async def test_standard_fields_and_timestamp_alias(collector, tmp_path):
    path = tmp_path / "tool.jsonl"
    records = [
        {
            "timestamp": "2026-09-13T08:00:00+08:00",
            "level": "info",
            "module": "collection",
            "event": "collect",
            "workflow_id": "workflow",
            "session_id": "first",
            "message": "中文\n第二行",
            "extra": {"credential": "secret"},
        },
        {
            "time": "2026-09-13T01:00:00Z",
            "timestamp": "invalid-but-unused-alias",
            "message": "canonical time wins",
        },
    ]
    encoded = b"".join(line(record) for record in records)
    path.write_bytes(encoded)
    result = await collector.collect({}, {}, context(path))
    assert result.status == "success"
    assert result.count == 2
    assert result.items[0]["time"] == "2026-09-13T00:00:00Z"
    assert result.items[0]["message"] == "中文\n第二行"
    assert result.items[1]["time"] == "2026-09-13T01:00:00Z"
    assert all(set(item) <= set(collector.fields) for item in result.items)
    assert [json.loads(item) for item in result.text.splitlines()] == result.items
    assert "secret" not in result.model_dump_json()
    assert result.metadata["bytes_read"] == len(encoded)
    assert result.metadata["ignored_incomplete_tail"] is False
    assert (
        not {"raw_count", "total_count", "original_count", "filtered_count"}
        & result.metadata.keys()
    )


async def test_filters_are_inclusive_and_preserve_file_order(collector, tmp_path):
    path = tmp_path / "tool.jsonl"
    records = [
        {
            "time": "2026-09-13T03:00:00Z",
            "level": "INFO",
            "module": "a",
            "session_id": "s",
            "message": "third",
        },
        {
            "time": "2026-09-13T01:00:00Z",
            "level": "INFO",
            "module": "a",
            "session_id": "s",
            "message": "first",
        },
        {
            "time": "2026-09-13T02:00:00Z",
            "level": "info",
            "module": "a",
            "session_id": "s",
            "message": "second",
        },
        {
            "time": "2026-09-13T02:00:00Z",
            "level": "ERROR",
            "module": "a",
            "session_id": "s",
            "message": "wrong level",
        },
        {
            "time": "2026-09-13T02:00:00Z",
            "level": "INFO",
            "module": "A",
            "session_id": "s",
            "message": "wrong module",
        },
        {
            "time": "2026-09-13T02:00:00Z",
            "level": "INFO",
            "module": "a",
            "session_id": "other",
            "message": "wrong session",
        },
        {"level": "INFO", "module": "a", "session_id": "s", "message": "no timestamp"},
    ]
    path.write_bytes(b"".join(line(record) for record in records))
    result = await collector.collect(
        {},
        {
            "levels": ["Info"],
            "modules": ["a"],
            "session_id": "s",
            "start_time": "2026-09-13T10:00:00+08:00",
            "end_time": "2026-09-13T03:00:00Z",
            "fields": ["message"],
        },
        context(path),
    )
    assert result.status == "success"
    assert result.items == [{"message": "third"}, {"message": "second"}]
    assert result.count == 2


async def test_grouping_keeps_event_count_and_first_appearance_order(collector, tmp_path):
    path = tmp_path / "tool.jsonl"
    path.write_bytes(
        b"".join(
            line(record)
            for record in [
                {"level": "WARN", "message": "first"},
                {"level": "INFO", "message": "second"},
                {"level": "WARN", "message": "third"},
                {"message": "missing level"},
            ]
        )
    )
    result = await collector.collect(
        {}, {"fields": ["message"], "group_by": "level"}, context(path)
    )
    assert result.count == 4
    assert len(result.items) == 3
    assert [group["value"] for group in result.items] == ["WARN", "INFO", None]
    assert result.items[0] == {
        "group_by": "level",
        "value": "WARN",
        "items": [{"message": "first"}, {"message": "third"}],
    }


async def test_tail_line_limit_precedes_filters(collector, tmp_path):
    path = tmp_path / "tool.jsonl"
    path.write_bytes(
        line({"level": "ERROR", "message": "old"})
        + line({"level": "INFO", "message": "newer"})
        + line({"level": "INFO", "message": "newest"})
    )
    result = await collector.collect({"max_lines": 2}, {}, context(path))
    assert [item["message"] for item in result.items] == ["newer", "newest"]
    assert result.metadata["line_limit_reached"] is True
    filtered = await collector.collect({"max_lines": 2}, {"levels": ["ERROR"]}, context(path))
    assert filtered.status == "filtered_empty"
    assert filtered.count == 0


@pytest.mark.parametrize(
    ("data", "setters", "status"),
    [
        (b"", {}, "empty"),
        (b"", {"fields": []}, "empty"),
        (b"{}\n", {}, "filtered_empty"),
        (b'{"extra": 1}\n', {}, "filtered_empty"),
        (b'{"message": "exists"}\n', {"fields": []}, "filtered_empty"),
        (b'{"message": "exists"}\n', {"fields": ["event"]}, "filtered_empty"),
        (b'{"message": "exists"}\n', {"levels": ["ERROR"]}, "filtered_empty"),
        (b'{"message": "exists"}\n', {"levels": [], "modules": []}, "success"),
    ],
)
async def test_empty_and_projection_states(collector, tmp_path, data, setters, status):
    path = tmp_path / "tool.jsonl"
    path.write_bytes(data)
    result = await collector.collect({}, setters, context(path))
    assert result.status == status
    assert result.error is None
    if status != "success":
        assert result.count == 0
        assert result.items == []
        assert result.text == ""


@pytest.mark.parametrize("unfinished", [b'{"message": "unfinished', b"\xff secret partial", b"{}"])
async def test_incomplete_tail_is_ignored_without_parsing(collector, tmp_path, unfinished):
    path = tmp_path / "tool.jsonl"
    path.write_bytes(line({"message": "complete"}) + unfinished)
    result = await collector.collect({}, {}, context(path))
    assert result.status == "success"
    assert result.items == [{"message": "complete"}]
    assert result.metadata["ignored_incomplete_tail"] is True
    assert "secret" not in result.model_dump_json()
    path.write_bytes(unfinished)
    empty = await collector.collect({}, {}, context(path))
    assert empty.status == "empty"
    assert empty.metadata["ignored_incomplete_tail"] is True


async def test_byte_budget_fragment_is_not_reported_as_corrupt(collector, tmp_path):
    path = tmp_path / "tool.jsonl"
    complete = line({"message": "complete"})
    path.write_bytes(b"invalid secret prefix" * 100 + b"\n" + complete)
    budget = len(complete) + 20
    result = await collector.collect({"max_bytes": budget}, {}, context(path))
    assert result.status == "success"
    assert result.items == [{"message": "complete"}]
    assert result.metadata["bytes_read"] == budget
    assert result.metadata["byte_limit_reached"] is True
    assert result.metadata["ignored_leading_fragment"] is True


async def test_actual_cumulative_reads_are_bounded_and_start_at_tail(
    collector, tmp_path, monkeypatch
):
    path = tmp_path / "tool.jsonl"
    encoded = b"".join(line({"message": f"{index}:" + "x" * 900}) for index in range(400))
    path.write_bytes(encoded)
    original_read = os.read
    original_fstat = os.fstat
    reads = []
    descriptors = set()

    def observed_read(fd, size):
        position = os.lseek(fd, 0, os.SEEK_CUR)
        descriptors.add(fd)
        data = original_read(fd, size)
        reads.append((position, size, len(data)))
        return data

    monkeypatch.setattr(logs.os, "read", observed_read)
    budget = 80_000
    result = await collector.collect({"max_bytes": budget, "max_lines": 10_000}, {}, context(path))
    assert result.status == "success"
    assert len(reads) == 2
    assert sum(actual for _, _, actual in reads) == budget
    assert sum(requested for _, requested, _ in reads) <= budget
    assert all(position >= len(encoded) - budget for position, _, _ in reads)
    assert all(requested <= 64 * 1024 for _, requested, _ in reads)
    assert result.metadata["bytes_read"] == budget
    assert result.items[-1]["message"].startswith("399:")
    assert result.count == len(result.items)
    for fd in descriptors:
        with pytest.raises(OSError):
            original_fstat(fd)


@pytest.mark.parametrize(
    "corrupt",
    [
        b"not-json secret\n",
        b"[]\n",
        b"\n",
        b'{"message": NaN}\n',
        b'{"message": 1e999}\n',
        b'{"message": "\xff secret"}\n',
        b'{"time": "secret invalid date", "message": "test"}\n',
        b'{"time": "2026-09-13T01:00:00", "message": "test"}\n',
    ],
)
async def test_complete_corruption_is_failed_with_only_safe_position(collector, tmp_path, corrupt):
    path = tmp_path / "tool.jsonl"
    preceding = line({"message": "valid preceding record"})
    path.write_bytes(preceding + corrupt)
    result = await collector.collect({}, {}, context(path))
    assert result.status == "failed"
    assert result.count == 0 and result.items == [] and result.text == ""
    assert result.error.code == "logs_corrupt"
    assert result.error.details["byte_offset"] == len(preceding)
    assert "secret" not in result.model_dump_json()
    assert str(path) not in result.model_dump_json()


async def test_all_complete_lines_in_read_window_are_validated(collector, tmp_path):
    path = tmp_path / "tool.jsonl"
    path.write_bytes(b"broken complete event\n" + line({"message": "latest"}))
    result = await collector.collect({"max_lines": 1}, {}, context(path))
    assert result.status == "failed"
    assert result.error.details["byte_offset"] == 0


@pytest.mark.parametrize("configured", [None, "", "missing-file"])
async def test_absent_logs_are_missing(collector, tmp_path, configured):
    path = tmp_path / configured if configured else configured
    result = await collector.collect({}, {}, context(path))
    assert result.status == "missing"
    assert result.error.code == "logs_missing"


async def test_permission_error_does_not_echo_path_or_exception(collector, tmp_path, monkeypatch):
    path = tmp_path / "tool.jsonl"
    path.write_bytes(line({"message": "exists"}))

    def forbidden_open(*args, **kwargs):
        raise PermissionError("secret access token and private path")

    monkeypatch.setattr(logs.os, "open", forbidden_open)
    result = await collector.collect({}, {}, context(path))
    assert result.status == "failed"
    assert result.error.code == "logs_permission_denied"
    assert "secret" not in result.model_dump_json()


async def test_nonregular_files_are_rejected_before_open(collector, tmp_path, monkeypatch):
    def forbidden_open(*args, **kwargs):
        raise AssertionError("a nonregular path must not be opened")

    monkeypatch.setattr(logs.os, "open", forbidden_open)
    directory = await collector.collect({}, {}, context(tmp_path))
    assert directory.error.code == "logs_not_regular"
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "pipe"
        os.mkfifo(fifo)
        result = await asyncio.wait_for(collector.collect({}, {}, context(fifo)), timeout=1)
        assert result.status == "failed"
        assert result.error.code == "logs_not_regular"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is a POSIX facility")
async def test_fifo_replacement_between_stat_and_open_cannot_block(
    collector, tmp_path, monkeypatch
):
    path = tmp_path / "tool.jsonl"
    path.write_bytes(line({"message": "before"}))
    original_open = os.open
    original_fstat = os.fstat
    opened_fds = []

    def replace_before_open(filename, flags):
        path.unlink()
        os.mkfifo(path)
        assert flags & os.O_NONBLOCK
        fd = original_open(filename, flags)
        opened_fds.append(fd)
        return fd

    monkeypatch.setattr(logs.os, "open", replace_before_open)
    result = await asyncio.wait_for(collector.collect({}, {}, context(path)), timeout=1)
    assert result.status == "failed"
    assert result.error.code == "logs_interrupted"
    for fd in opened_fds:
        with pytest.raises(OSError):
            original_fstat(fd)


@pytest.mark.parametrize("mutation", ["rotate", "truncate", "rewrite", "unlink"])
async def test_file_changes_interrupt_read_and_close_fd(collector, tmp_path, monkeypatch, mutation):
    path = tmp_path / "tool.jsonl"
    original = line({"message": "original"})
    path.write_bytes(original)
    original_read = os.read
    original_fstat = os.fstat
    observed_fds = []

    def mutate_during_read(fd, size):
        data = original_read(fd, size)
        observed_fds.append(fd)
        if mutation == "rotate":
            path.rename(path.with_suffix(".old"))
            path.write_bytes(line({"message": "replacement"}))
        elif mutation == "truncate":
            path.write_bytes(b"")
        elif mutation == "rewrite":
            previous = path.stat()
            path.write_bytes(original.replace(b"original", b"replaced"))
            os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000))
        else:
            path.unlink()
        return data

    monkeypatch.setattr(logs.os, "read", mutate_during_read)
    result = await collector.collect({}, {}, context(path))
    assert result.status == "failed"
    assert result.error.code == "logs_interrupted"
    assert result.count == 0 and not result.items and not result.text
    for fd in observed_fds:
        with pytest.raises(OSError):
            original_fstat(fd)


async def test_append_after_open_is_ignored_without_interrupting(collector, tmp_path, monkeypatch):
    path = tmp_path / "tool.jsonl"
    original = line({"message": "original"})
    path.write_bytes(original)
    original_read = os.read

    def append_during_read(fd, size):
        data = original_read(fd, size)
        with path.open("ab") as output:
            output.write(line({"message": "appended"}))
        return data

    monkeypatch.setattr(logs.os, "read", append_during_read)
    result = await collector.collect({}, {}, context(path))
    assert result.status == "success"
    assert result.items == [{"message": "original"}]
    assert result.metadata["snapshot_size_bytes"] == len(original)
    assert result.metadata["bytes_read"] == len(original)
    assert result.metadata["appended_during_read"] is True


async def test_shrink_after_observed_append_is_still_interrupted(collector, tmp_path, monkeypatch):
    path = tmp_path / "tool.jsonl"
    original = b"".join(line({"message": "x" * 900}) for _ in range(200))
    path.write_bytes(original)
    original_read = os.read
    calls = 0

    def change_size(fd, size):
        nonlocal calls
        data = original_read(fd, size)
        calls += 1
        if calls == 1:
            with path.open("ab") as output:
                output.write(line({"message": "new tail"}))
        else:
            with path.open("r+b") as output:
                output.truncate(len(original) + 1)
        return data

    monkeypatch.setattr(logs.os, "read", change_size)
    result = await collector.collect({"max_lines": 10_000}, {}, context(path))
    assert result.status == "failed"
    assert result.error.code == "logs_interrupted"
    assert result.error.details["reason"] == "truncated"


async def test_short_read_is_not_published_as_partial_success(collector, tmp_path, monkeypatch):
    path = tmp_path / "tool.jsonl"
    path.write_bytes(line({"message": "complete"}))
    original_read = os.read
    original_fstat = os.fstat
    opened_fds = []

    def short_read(fd, size):
        opened_fds.append(fd)
        return original_read(fd, size - 1)

    monkeypatch.setattr(logs.os, "read", short_read)
    result = await collector.collect({}, {}, context(path))
    assert result.status == "failed"
    assert result.error.code == "logs_interrupted"
    assert result.error.details["reason"] == "short_read"
    for fd in opened_fds:
        with pytest.raises(OSError):
            original_fstat(fd)


async def test_read_error_closes_descriptor_and_redacts_error(collector, tmp_path, monkeypatch):
    path = tmp_path / "tool.jsonl"
    path.write_bytes(line({"message": "exists"}))
    original_fstat = os.fstat
    opened_fds = []

    def failing_read(fd, size):
        opened_fds.append(fd)
        raise OSError("secret failure details")

    monkeypatch.setattr(logs.os, "read", failing_read)
    result = await collector.collect({}, {}, context(path))
    assert result.status == "failed"
    assert result.error.code == "logs_read_failed"
    assert "secret" not in result.model_dump_json()
    for fd in opened_fds:
        with pytest.raises(OSError):
            original_fstat(fd)


async def test_cancel_propagates_and_worker_closes_after_inflight_read(
    collector, tmp_path, monkeypatch
):
    path = tmp_path / "tool.jsonl"
    path.write_bytes(b"".join(line({"message": "x" * 1000}) for _ in range(200)))
    started = Event()
    release = Event()
    closed = Event()
    original_read = os.read
    original_close = os.close
    original_fstat = os.fstat
    opened_fds = []
    read_count = 0

    def paused_read(fd, size):
        nonlocal read_count
        opened_fds.append(fd)
        read_count += 1
        started.set()
        if not release.wait(timeout=3):
            raise AssertionError("test never released its bounded read")
        return original_read(fd, size)

    def observed_close(fd):
        original_close(fd)
        if fd in opened_fds:
            closed.set()

    monkeypatch.setattr(logs.os, "read", paused_read)
    monkeypatch.setattr(logs.os, "close", observed_close)
    task = asyncio.create_task(collector.collect({"max_lines": 10_000}, {}, context(path)))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 2), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not closed.is_set()
    finally:
        release.set()
    assert await asyncio.wait_for(asyncio.to_thread(closed.wait, 2), timeout=3)
    assert read_count == 1
    for fd in opened_fds:
        with pytest.raises(OSError):
            original_fstat(fd)


async def test_concurrent_calls_keep_paths_and_results_separate(collector, tmp_path):
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_bytes(line({"message": "first"}))
    second.write_bytes(line({"message": "second"}))
    results = await asyncio.gather(
        collector.collect({}, {}, context(first)),
        collector.collect({}, {}, context(second)),
    )
    assert results[0].items == [{"message": "first"}]
    assert results[1].items == [{"message": "second"}]
    results[0].items[0]["message"] = "changed"
    assert results[1].items == [{"message": "second"}]
