"""Bounded JSON Lines log collection from the invocation's fixed log path.

``time`` is the public timestamp field; an input ``timestamp`` is its fallback.
The selected events retain file order, regardless of their timestamps. A read
is bounded to the size observed on opening the file, ignoring later appends.
Rotation, truncation and observed rewrites without growth interrupt the read;
this is not an atomic snapshot against arbitrary concurrent in-place writes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
from collections import deque
from copy import deepcopy
from datetime import UTC, datetime
from threading import Event
from typing import Any

from pydantic import TypeAdapter, ValidationError

from logagent.errors import LogAgentError, exception_error
from logagent.models import ID, CollectionContext, CollectorOutput, JSONObject
from logagent.schema import validate_instance

_FIELDS = ["time", "level", "module", "event", "workflow_id", "session_id", "message"]
_READ_BLOCK = 64 * 1024
_MAX_LINES = 10_000
_MAX_BYTES = 16 * 1024 * 1024
_JSON_OBJECT = TypeAdapter(JSONObject)
_SESSION_ID = TypeAdapter(ID)
logger = logging.getLogger(__name__)


class _ReadCancelled(Exception):
    """A cancelled caller has asked its bounded worker to finish cleanup."""


def _check_cancelled(cancelled: Event) -> None:
    if cancelled.is_set():
        raise _ReadCancelled


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("A log timestamp must be a string")
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("A log timestamp must include its timezone")
    return result.astimezone(UTC)


def _invalid_parameter(name: str, reason: str, *, group: str = "setters") -> LogAgentError:
    return LogAgentError(
        "invalid_config",
        "日志采集参数无效",
        {"errors": [{"path": [group, name], "reason": reason}]},
    )


def _check_file_change(before: os.stat_result, after: os.stat_result) -> None:
    reason = None
    if not stat.S_ISREG(after.st_mode):
        reason = "type_changed"
    elif (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        reason = "rotated"
    elif after.st_size < before.st_size:
        reason = "truncated"
    elif after.st_size == before.st_size and (
        after.st_mtime_ns != before.st_mtime_ns or after.st_ctime_ns != before.st_ctime_ns
    ):
        reason = "rewritten"
    if reason is not None:
        raise LogAgentError(
            "logs_interrupted", "读取期间日志文件发生轮转或改写", {"reason": reason}
        )


def _ensure_unchanged(fd: int, path: str, previous: os.stat_result) -> os.stat_result:
    try:
        current_fd = os.fstat(fd)
        current_path = os.stat(path)
    except OSError as exc:
        raise LogAgentError(
            "logs_interrupted",
            "读取期间日志文件不可用",
            {"reason": "source_unavailable", "exception_type": type(exc).__name__},
        ) from None
    _check_file_change(previous, current_fd)
    _check_file_change(current_fd, current_path)
    return current_path


def _bounded_tail(
    path: str, max_lines: int, max_bytes: int, cancelled: Event
) -> tuple[bytes, int, JSONObject]:
    """Read raw, unbuffered blocks backwards; stat calls never read content.

    A leading fragment is always excluded unless its start is the file start.
    This deliberately discards an ambiguous boundary line instead of spending
    an extra byte outside max_bytes to inspect its preceding delimiter.
    """
    _check_cancelled(cancelled)
    logger.debug("reading bounded JSONL log path=%s max_lines=%d max_bytes=%d", path, max_lines, max_bytes)
    try:
        before_open = os.stat(path)
    except FileNotFoundError:
        raise LogAgentError("logs_missing", "日志文件不存在", {"reason": "not_found"}) from None
    if not stat.S_ISREG(before_open.st_mode):
        raise LogAgentError(
            "logs_not_regular", "日志来源必须是普通文件", {"reason": "not_regular_file"}
        )

    # O_NONBLOCK also prevents a FIFO swapped in after stat from blocking open.
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise LogAgentError(
            "logs_interrupted", "打开日志时来源消失", {"reason": "removed_before_open"}
        ) from None
    try:
        _check_cancelled(cancelled)
        opened = os.fstat(fd)
        _check_file_change(before_open, opened)
        observed = _ensure_unchanged(fd, path, opened)
        end = opened.st_size
        chunks: list[bytes] = []
        bytes_read = 0
        delimiters = 0
        while end and bytes_read < max_bytes:
            _check_cancelled(cancelled)
            length = min(_READ_BLOCK, end, max_bytes - bytes_read)
            offset = end - length
            os.lseek(fd, offset, os.SEEK_SET)
            block = os.read(fd, length)
            bytes_read += len(block)
            _check_cancelled(cancelled)
            observed = _ensure_unchanged(fd, path, observed)
            if len(block) != length:
                raise LogAgentError(
                    "logs_interrupted",
                    "日志读取未取得预期范围",
                    {"reason": "short_read", "byte_offset": offset},
                )
            chunks.append(block)
            delimiters += block.count(b"\n")
            end = offset
            # One delimiter establishes the leading boundary, including when
            # the final event is still being written and has no closing LF.
            if delimiters >= max_lines + 1:
                break
        _check_cancelled(cancelled)
        observed = _ensure_unchanged(fd, path, observed)
        data = b"".join(reversed(chunks))
    finally:
        os.close(fd)

    metadata: JSONObject = {
        "bytes_read": bytes_read,
        "max_bytes": max_bytes,
        "max_lines": max_lines,
        "snapshot_size_bytes": opened.st_size,
        "appended_during_read": observed.st_size > opened.st_size,
        "byte_limit_reached": end > 0 and bytes_read == max_bytes,
        "ignored_leading_fragment": end > 0,
        "ignored_incomplete_tail": bool(data) and not data.endswith(b"\n"),
        "line_limit_reached": False,
        "format": "jsonl",
        "order": "file_ascending",
    }
    if end > 0:
        boundary = data.find(b"\n")
        if boundary == -1:
            return b"", opened.st_size, metadata
        end += boundary + 1
        data = data[boundary + 1 :]
    if data and not data.endswith(b"\n"):
        data = data[: data.rfind(b"\n") + 1]
    return data, end, metadata


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON constants are not log events")


def _parse_event(line: bytes, byte_offset: int) -> JSONObject:
    try:
        decoded = line.decode("utf-8")
    except UnicodeDecodeError:
        raise LogAgentError(
            "logs_corrupt",
            "日志完整行不是有效 UTF-8",
            {"byte_offset": byte_offset, "reason": "invalid_utf8"},
        ) from None
    try:
        record = json.loads(decoded, parse_constant=_reject_constant)
        record = _JSON_OBJECT.validate_python(record)
    except (ValueError, ValidationError, RecursionError):
        raise LogAgentError(
            "logs_corrupt",
            "日志完整行不是有效 JSON 对象",
            {"byte_offset": byte_offset, "reason": "invalid_json_object"},
        ) from None

    event = {field: record[field] for field in _FIELDS if field in record}
    time_key = "time" if "time" in record else "timestamp"
    if time_key in record:
        try:
            event["time"] = _timestamp(record[time_key]).isoformat().replace("+00:00", "Z")
        except (ValueError, OverflowError):
            raise LogAgentError(
                "logs_corrupt",
                "日志时间必须包含有效时区",
                {"byte_offset": byte_offset, "reason": "invalid_time", "field": time_key},
            ) from None
    return event


def _matches(event: JSONObject, setters: JSONObject) -> bool:
    levels = setters.get("levels", [])
    if levels and (
        not isinstance(event.get("level"), str)
        or event["level"].upper() not in {level.upper() for level in levels}
    ):
        return False
    modules = setters.get("modules", [])
    if modules and event.get("module") not in modules:
        return False
    session_id = setters.get("session_id")
    if session_id is not None and event.get("session_id") != session_id:
        return False
    start_time = setters.get("start_time")
    end_time = setters.get("end_time")
    if start_time is not None or end_time is not None:
        if "time" not in event:
            return False
        moment = _timestamp(event["time"])
        if start_time is not None and moment < _timestamp(start_time):
            return False
        if end_time is not None and moment > _timestamp(end_time):
            return False
    return True


def _format_events(events: list[JSONObject], setters: JSONObject) -> tuple[list[JSONObject], int]:
    fields = setters.get("fields", _FIELDS)
    group_by = setters.get("group_by")
    items: list[JSONObject] = []
    groups: dict[str, JSONObject] = {}
    count = 0
    for event in events:
        if not _matches(event, setters):
            continue
        projected = {field: event[field] for field in fields if field in event}
        if not projected:
            continue
        count += 1
        if group_by is None:
            items.append(projected)
            continue
        value = event.get(group_by)
        key = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if key not in groups:
            group: JSONObject = {"group_by": group_by, "value": value, "items": []}
            groups[key] = group
            items.append(group)
        groups[key]["items"].append(projected)
    return items, count


def _collect_file(
    path: str, max_lines: int, max_bytes: int, setters: JSONObject, cancelled: Event
) -> CollectorOutput:
    try:
        data, byte_offset, metadata = _bounded_tail(path, max_lines, max_bytes, cancelled)
        events: deque[JSONObject] = deque(maxlen=max_lines)
        if data:
            lines = data.split(b"\n")[:-1]
            metadata["line_limit_reached"] = len(lines) > max_lines
            for line in lines:
                _check_cancelled(cancelled)
                # Validate every complete line in the read window, including
                # block overlap before the selected max_lines suffix.
                events.append(_parse_event(line, byte_offset))
                byte_offset += len(line) + 1
        if not events:
            return CollectorOutput(status="empty", metadata=metadata)
        _check_cancelled(cancelled)
        items, count = _format_events(list(events), setters)
        if not count:
            return CollectorOutput(status="filtered_empty", metadata=metadata)
        text = "\n".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False) for item in items
        )
        _check_cancelled(cancelled)
        return CollectorOutput(
            status="success", items=items, text=text, count=count, metadata=metadata
        )
    except LogAgentError as exc:
        return CollectorOutput(
            status="missing" if exc.code == "logs_missing" else "failed", error=exc.info
        )
    except PermissionError as exc:
        return CollectorOutput(
            status="failed",
            error=exception_error(exc, code="logs_permission_denied", message="日志文件无读取权限"),
        )
    except (OSError, ValueError) as exc:
        return CollectorOutput(
            status="failed",
            error=exception_error(exc, code="logs_read_failed", message="日志文件读取失败"),
        )


class LogsCollector:
    name = "logs"
    execution = "read"
    id_prefix = "logs"
    description = "读取有界 JSONL 日志尾部，按声明筛选、投影和分组；保留文件中的事件顺序。"
    fields = list(_FIELDS)
    count_unit = "events"
    options_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "description": "日志路径来自 CollectionContext.log_path；读取最多指定字节和最近完整行。",
        "properties": {
            "max_lines": {
                "x-logagent-workflow": True,
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_LINES,
                "default": 200,
                "description": "选择尾部最近多少条完整事件（最多 10000）；先限行再应用 Setter。",
            },
            "max_bytes": {
                "x-logagent-workflow": True,
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_BYTES,
                "default": 256 * 1024,
                "description": "所有文件内容 read 的累计字节预算，默认 256 KiB，最多 16 MiB。",
            },
        },
        "additionalProperties": False,
    }
    setters_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "description": "先过滤、再字段投影和分组；输出保持文件顺序，不按事件时间重排。",
        "properties": {
            "levels": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 64},
                "uniqueItems": True,
                "maxItems": 64,
                "default": [],
                "description": "按 level 不区分大小写匹配；空列表不限制等级。",
            },
            "modules": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 200},
                "uniqueItems": True,
                "maxItems": 200,
                "default": [],
                "description": "按 module 精确匹配；空列表不限制模块。",
            },
            "session_id": {
                "type": ["string", "null"],
                "pattern": "^[A-Za-z0-9_-]{1,80}$",
                "default": None,
                "description": "只选择此 session 的事件；null 不限制 session。",
            },
            "start_time": {
                "type": ["string", "null"],
                "format": "date-time",
                "default": None,
                "description": "含端点的起始时间，须为带时区的 RFC 3339 时间；按 UTC 比较。",
            },
            "end_time": {
                "type": ["string", "null"],
                "format": "date-time",
                "default": None,
                "description": "含端点的结束时间，不早于 start_time；null 不限制。",
            },
            "fields": {
                "type": "array",
                "items": {"type": "string", "enum": list(_FIELDS)},
                "uniqueItems": True,
                "maxItems": len(_FIELDS),
                "default": list(_FIELDS),
                "description": (
                    "输出字段；空列表不产生可消费内容。time 缺失时接受输入 timestamp，"
                    "统一输出 UTC time；未声明字段不投影。"
                ),
            },
            "group_by": {
                "type": ["string", "null"],
                "enum": [*_FIELDS, None],
                "default": None,
                "description": (
                    "按投影前此字段的值分组，缺字段归 null 组；组按首次出现排序，"
                    "成员保持文件顺序，count 仍按事件计数。"
                ),
            },
        },
        "additionalProperties": False,
    }

    def validate(self, options: JSONObject, setters: JSONObject) -> None:
        """Pure semantic validation, also usable by a configuration caller."""
        validate_instance(options, self.options_schema, path=["options"])
        validate_instance(setters, self.setters_schema, path=["setters"])
        for name in ("max_lines", "max_bytes"):
            if name in options and type(options[name]) is not int:
                raise _invalid_parameter(name, "必须为整数，不接受浮点数或布尔值", group="options")
        if setters.get("session_id") is not None:
            try:
                _SESSION_ID.validate_python(setters["session_id"])
            except ValidationError:
                raise _invalid_parameter("session_id", "必须为有效的 session 标识") from None
        start = setters.get("start_time")
        end = setters.get("end_time")
        for name, value in (("start_time", start), ("end_time", end)):
            if value is not None:
                try:
                    _timestamp(value)
                except (ValueError, OverflowError):
                    raise _invalid_parameter(name, "必须为有效的带时区时间") from None
        if start is not None and end is not None and _timestamp(start) > _timestamp(end):
            raise _invalid_parameter("end_time", "不得早于 start_time")

    async def collect(
        self, options: JSONObject, setters: JSONObject, context: CollectionContext
    ) -> CollectorOutput:
        self.validate(options, setters)
        if context.log_path is None or not context.log_path.strip():
            return CollectorOutput(
                status="missing",
                error=LogAgentError(
                    "logs_missing", "未配置日志文件", {"reason": "not_configured"}
                ).info,
            )
        cancelled = Event()
        try:
            return await asyncio.to_thread(
                _collect_file,
                context.log_path,
                options.get("max_lines", 200),
                options.get("max_bytes", 256 * 1024),
                deepcopy(setters),
                cancelled,
            )
        finally:
            # Cancelling an await does not stop a thread. Its next checkpoint
            # stops further bounded reads; the worker always closes its fd.
            cancelled.set()
