"""生命周期 JSON 日志组件测试。

隔离并恢复全局 logger，以真实临时文件检查 Handler 唯一所有权、幂等启停、
结构化字段、脱敏、轮转及 UTF-8 字节上限；注入写入故障，断言健康诊断
保留脱敏原因，修复后可恢复。避免将不可控对象和异常正文格式化入日志。
"""

from __future__ import annotations

import io
import json
import logging
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from workflowweave.lifecycle.logging import JsonLogSink, RedactingJsonFormatter

_MARKER = "_workflowweave_lifecycle_handler"
_LOGGER_NAME = "workflowweave"


@pytest.fixture(autouse=True)
def _isolate_logger():
    logger = logging.getLogger(_LOGGER_NAME)
    previous_handlers = list(logger.handlers)
    previous_level = logger.level
    previous_propagate = logger.propagate
    yield
    for handler in tuple(logger.handlers):
        if getattr(handler, _MARKER, False):
            logger.removeHandler(handler)
            handler.close()
    logger.handlers[:] = previous_handlers
    logger.setLevel(previous_level)
    logger.propagate = previous_propagate


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_owned_lifecycle_restores_logger_and_rejects_conflict(tmp_path: Path) -> None:
    logger = logging.getLogger(_LOGGER_NAME)
    original_level = logging.WARNING
    original_propagate = True
    logger.setLevel(original_level)
    logger.propagate = original_propagate

    path = tmp_path / "owned" / "app.jsonl"
    sink = JsonLogSink(path, max_bytes=1024, backup_count=1)
    assert sink.error is None
    assert sink.check().code == "logging_not_started"

    sink.start()
    sink.start()
    assert logger.level == logging.INFO
    assert logger.propagate is False
    assert sink.check() is None
    logger.info("first_event", extra={"event": "first_event", "session_id": "session-1"})

    conflicting_path = tmp_path / "other" / "app.jsonl"
    conflicting = JsonLogSink(conflicting_path, max_bytes=1024, backup_count=1)
    with pytest.raises(RuntimeError, match="already owns"):
        conflicting.start()
    assert conflicting.error is None
    assert conflicting.check().code == "logging_not_started"
    assert not conflicting_path.parent.exists()

    logger.info(
        "second_event",
        extra={
            "event": "second_event",
            "workflow_id": "workflow-1",
            "source_id": "source-1",
            "task_id": "task-1",
            "channel_id": "channel-1",
            "output_id": "output-1",
        },
    )
    sink.close()
    sink.close()
    assert logger.level == original_level
    assert logger.propagate is original_propagate
    assert sink.check().code == "logging_closed"

    sink.start()
    logger.info("third_event", extra={"event": "third_event"})
    sink.close()

    records = _records(path) + _records(Path(f"{path}.1"))
    events = {record["event"] for record in records}
    assert {"first_event", "second_event", "third_event"} <= events
    second = next(record for record in records if record["event"] == "second_event")
    assert second["workflow_id"] == "workflow-1"
    assert second["source_id"] == "source-1"
    assert second["task_id"] == "task-1"
    assert second["channel_id"] == "channel-1"
    assert second["output_id"] == "output-1"


def test_json_logging_is_bounded_redacted_and_rotates(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        JsonLogSink(tmp_path / "zero.jsonl", backup_count=0)
    with pytest.raises(ValueError, match="at least"):
        JsonLogSink(tmp_path / "small.jsonl", max_bytes=1, backup_count=1)

    class Explosive:
        def __str__(self) -> str:
            raise AssertionError("record arguments and extras must not be stringified")

    path = tmp_path / "bounded.jsonl"
    max_bytes = 256
    sink = JsonLogSink(path, max_bytes=max_bytes, backup_count=1)
    sink.start()
    logger = logging.getLogger("workflowweave.test")
    try:
        for index in range(12):
            logger.info(
                "authorization=Bearer super-secret-token password=hidden-value",
                extra={
                    "event": f"event-{index}",
                    "session_id": "session-1",
                    "source_id": "source-1",
                    "task_id": "task-1",
                    "channel_id": "channel-1",
                    "output_id": "output-1",
                    "workflow_id": "workflow-1",
                    "unsafe_extra": Explosive(),
                },
            )
        logger.info("prompt: %s", Explosive(), extra={"event": "argument_object"})
        try:
            raise RuntimeError("raw-exception-secret")
        except RuntimeError:
            logger.exception("exception_event", extra={"event": "exception_event"})
    finally:
        sink.close()

    paths = [path, Path(f"{path}.1")]
    content = "".join(item.read_text(encoding="utf-8") for item in paths if item.exists())
    assert Path(f"{path}.1").exists()
    assert "super-secret-token" not in content
    assert "hidden-value" not in content
    assert "raw-exception-secret" not in content
    assert "unsupported value omitted" not in content
    for item in paths:
        if not item.exists():
            continue
        for line in item.read_text(encoding="utf-8").splitlines():
            assert len(line.encode("utf-8")) + 1 <= max_bytes
            record = json.loads(line)
            assert {"time", "level", "module", "event", "message"} <= record.keys()
    exception_record = next(
        record
        for record in _records(path) + _records(Path(f"{path}.1"))
        if record["event"] == "exception_event"
    )
    assert exception_record["exception_type"] == "RuntimeError"


def test_unicode_json_is_valid_and_bounded_by_utf8_bytes() -> None:
    record = logging.LogRecord(
        name="workflowweave.测试",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="unicode_event",
        args=(),
        exc_info=None,
    )
    record.event = "unicode_event"
    record.session_id = "会话-😀"

    serialized = RedactingJsonFormatter(max_bytes=1024).format(record)
    decoded = json.loads(serialized)
    assert decoded["module"] == "workflowweave.测试"
    assert decoded["session_id"] == "会话-😀"

    max_bytes = len(serialized.encode("utf-8")) + 1
    exact = RedactingJsonFormatter(max_bytes=max_bytes).format(record)
    assert exact == serialized

    bounded = RedactingJsonFormatter(max_bytes=max_bytes - 1).format(record)
    assert len(bounded.encode("utf-8")) + 1 <= max_bytes - 1
    assert json.loads(bounded)["session_id"] == "会话-😀"


def test_write_failure_is_sanitized_and_recovers_through_check(tmp_path: Path) -> None:
    class BrokenStream:
        def seek(self, offset: int, whence: int = 0) -> int:
            return 0

        def tell(self) -> int:
            return 0

        def write(self, value: str) -> int:
            raise OSError("raw-secret-from-write")

        def flush(self) -> None:
            raise OSError("raw-secret-from-flush")

        def close(self) -> None:
            return None

    path = tmp_path / "failure.jsonl"
    sink = JsonLogSink(path, max_bytes=256, backup_count=1)
    sink.start()
    handler = sink._handler
    assert handler is not None
    original_stream = handler.stream
    handler.stream = BrokenStream()
    stderr = io.StringIO()
    try:
        with redirect_stderr(stderr):
            logging.getLogger("workflowweave.test").error(
                "write_event",
                extra={"event": "write_event", "session_id": "session-1"},
            )
        assert stderr.getvalue() == ""
        failure = sink.check()
        assert failure is not None
        assert failure.code == "logging_write_failed"
        assert failure.details["exception_type"] == "OSError"
        assert "raw-secret" not in failure.model_dump_json()

        handler.stream = original_stream
        assert sink.check() is None
        assert sink.error is None
    finally:
        handler.stream = original_stream
        sink.close()
