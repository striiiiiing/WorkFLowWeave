"""将日志整理为脱敏、字段受限且满足 UTF-8 字节预算的 JSON。"""

from __future__ import annotations

import logging
import math
import re
from datetime import UTC, datetime
from typing import Any

import orjson

_MAX_BYTES = 10 * 1024 * 1024
_MIN_MAX_BYTES = 128
_FIELD_MAX_BYTES = 256
_SUMMARY = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,159}$")
_CORRELATION_FIELDS = (
    "workflow_id",
    "session_id",
    "stage",
    "source_id",
    "task_id",
    "channel_id",
    "output_id",
    "error_code",
    "delivery_status",
    "delivery_uncertain",
    "status",
    "scope",
    "active_runs",
    "attempt",
    "will_retry",
    "status_code",
    "uncertain",
)
_OPTIONAL_JSON_FIELDS = ("message", *reversed(_CORRELATION_FIELDS), "exception_type")
_AUTHORIZATION = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/\-=]+")
_NAMED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|password|secret|token|authorization|credential|master[_-]?key)"
    r"\b\s*[:=]\s*([^\s,;]+)"
)
_URL_CREDENTIAL = re.compile(r"(?i)(https?://)([^/\s:@]+):([^@\s/]+)@")


def _truncate_text(value: str, max_bytes: int) -> str:
    """在字节预算内截断文本，保持合法 UTF-8，空间允许时保留省略号。"""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    if max_bytes <= 3:
        return encoded[:max_bytes].decode("utf-8", "ignore")
    return encoded[: max_bytes - 3].decode("utf-8", "ignore") + "..."


def _redact_text(value: str) -> str:
    """遮盖授权头、具名密钥及 HTTP URL 内嵌凭据等已知敏感模式。"""
    value = _AUTHORIZATION.sub(lambda match: f"{match.group(1)} [REDACTED]", value)
    value = _NAMED_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return _URL_CREDENTIAL.sub(lambda match: f"{match.group(1)}[REDACTED]@", value)


def _safe_value(value: Any, *, max_bytes: int = _FIELD_MAX_BYTES) -> Any:
    """仅保留有限基本类型并限制字符串长度，不调用任意对象的字符串转换。"""
    if type(value) is str:
        return _truncate_text(_redact_text(value), max_bytes)
    if type(value) is bool:
        return value
    if type(value) is int:
        if -(2**63) <= value <= 2**64 - 1:
            return value
        return "[integer omitted]"
    if type(value) is float:
        return value if math.isfinite(value) else None
    if value is None:
        return None
    return "[unsupported value omitted]"


def _safe_summary(record: logging.LogRecord) -> str:
    """仅接受无格式参数且符合摘要模式的字符串，其他内容用省略标记替代。

    不调用 getMessage，避免参数格式化执行任意 __str__ 并泄露业务正文。
    """
    if type(record.args) is not tuple or record.args:
        return "[formatted arguments omitted]"
    if type(record.msg) is str and _SUMMARY.fullmatch(record.msg):
        return _redact_text(record.msg)
    return "[message omitted]"


def _safe_event(record: logging.LogRecord) -> str:
    """保留符合摘要模式的事件名，缺失或无效时使用通用事件 log。"""
    event = record.__dict__.get("event")
    if type(event) is str and _SUMMARY.fullmatch(event):
        return _redact_text(event)
    return "log"


def _safe_timestamp(created: Any) -> str:
    """生成 UTC ISO 时间；类型、数值或平台范围无效时使用 Unix 纪元。"""
    if type(created) is int:
        if not -(2**63) <= created <= 2**63 - 1:
            return "1970-01-01T00:00:00Z"
    elif type(created) is float and math.isfinite(created):
        pass
    else:
        return "1970-01-01T00:00:00Z"
    try:
        timestamp = datetime.fromtimestamp(created, UTC)
    except (OSError, OverflowError, TypeError, ValueError):
        return "1970-01-01T00:00:00Z"
    return timestamp.isoformat().replace("+00:00", "Z")


def _dumps_if_within_limit(payload: dict[str, Any], limit: int) -> str | None:
    """序列化 JSON，超过 UTF-8 字节预算时返回 None，序列化异常直接传播。"""
    encoded = orjson.dumps(payload)
    if len(encoded) <= limit:
        return encoded.decode("utf-8")
    return None


def _bounded_json(payload: dict[str, Any], limit: int) -> str:
    """在副本上依次删除可选字段、缩短必需字段，使 JSON 满足字节预算。

    先舍弃消息，再按关联字段的逆序舍弃，最后舍弃异常类型；仍超限时缩短基础字段。
    若连最小记录也无法容纳则抛出 ValueError，不修改调用方的 payload。
    """
    candidate = dict(payload)
    encoded = _dumps_if_within_limit(candidate, limit)
    if encoded is not None:
        return encoded

    for field in _OPTIONAL_JSON_FIELDS:
        candidate.pop(field, None)
        encoded = _dumps_if_within_limit(candidate, limit)
        if encoded is not None:
            return encoded

    event = candidate.get("event", "log")
    module = candidate.get("module", "logagent")
    level = candidate.get("level", "INFO")
    timestamp = candidate.get("time", "1970-01-01T00:00:00Z")
    for event_bytes in (64, 32, 16, 8):
        candidate["event"] = _truncate_text(event, event_bytes) if type(event) is str else "log"
        candidate["module"] = _truncate_text(module, 16) if type(module) is str else "logagent"
        candidate["level"] = _truncate_text(level, 8) if type(level) is str else "INFO"
        candidate["time"] = (
            _truncate_text(timestamp, 32) if type(timestamp) is str else "1970-01-01T00:00:00Z"
        )
        encoded = _dumps_if_within_limit(candidate, limit)
        if encoded is not None:
            return encoded

    fallback = {
        "time": _truncate_text(str(timestamp), 24),
        "level": _truncate_text(str(level), 8),
        "module": "log",
        "event": "log",
    }
    encoded = _dumps_if_within_limit(fallback, limit)
    if encoded is None:
        raise ValueError("max_bytes is too small for a bounded JSON log record")
    return encoded


class RedactingJsonFormatter(logging.Formatter):
    """输出有大小上限的诊断摘要，省略格式化参数、异常正文和堆栈。"""

    def __init__(self, max_bytes: int = _MAX_BYTES) -> None:
        """校验整行字节预算，并为 handler 添加的换行符预留一个字节。"""
        if type(max_bytes) is not int or max_bytes < _MIN_MAX_BYTES:
            raise ValueError(f"max_bytes must be an integer at least {_MIN_MAX_BYTES}")
        super().__init__()
        self._limit = max_bytes - 1

    def format(self, record: logging.LogRecord) -> str:
        """仅序列化基础字段和允许的关联字段，异常只保留类型，返回不带换行的 JSON。"""
        payload: dict[str, Any] = {
            "time": _safe_timestamp(record.created),
            "level": _safe_value(record.levelname, max_bytes=16),
            "module": _safe_value(record.name, max_bytes=128),
            "event": _safe_event(record),
            "message": _safe_summary(record),
        }
        for field in _CORRELATION_FIELDS:
            if field in record.__dict__:
                payload[field] = _safe_value(record.__dict__[field])

        exc_info = record.__dict__.get("exc_info")
        if exc_info:
            exception_type = getattr(exc_info[0], "__name__", None)
            if type(exception_type) is str:
                payload["exception_type"] = _redact_text(_truncate_text(exception_type, 128))
        return _bounded_json(payload, self._limit)
