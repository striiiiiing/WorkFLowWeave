"""Owned standard-library JSON logging with bounded rotation and redaction."""

from __future__ import annotations

import logging
import math
import re
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import orjson

from logagent.models import ErrorInfo

_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5
_MIN_MAX_BYTES = 128
_FIELD_MAX_BYTES = 256
_HANDLER_MARKER = "_logagent_lifecycle_handler"
_HANDLER_OWNER = "_logagent_lifecycle_owner"
_LOGGER_NAME = "logagent"
_OWNERSHIP_LOCK = threading.RLock()
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
_AUTHORIZATION = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/\-=]+")
_NAMED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|password|secret|token|authorization|credential|master[_-]?key)"
    r"\b\s*[:=]\s*([^\s,;]+)"
)
_URL_CREDENTIAL = re.compile(r"(?i)(https?://)([^/\s:@]+):([^@\s/]+)@")


def _truncate_text(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    if max_bytes <= 3:
        return encoded[:max_bytes].decode("utf-8", "ignore")
    return encoded[: max_bytes - 3].decode("utf-8", "ignore") + "..."


def _redact_text(value: str) -> str:
    value = _AUTHORIZATION.sub(lambda match: f"{match.group(1)} [REDACTED]", value)
    value = _NAMED_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return _URL_CREDENTIAL.sub(lambda match: f"{match.group(1)}[REDACTED]@", value)


def _safe_value(value: Any, *, max_bytes: int = _FIELD_MAX_BYTES) -> Any:
    """Return only bounded primitives; arbitrary objects are never stringified."""
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
    # record.getMessage() can invoke arbitrary __str__ methods on arguments.
    if type(record.args) is not tuple or record.args:
        return "[formatted arguments omitted]"
    if type(record.msg) is str and _SUMMARY.fullmatch(record.msg):
        return _redact_text(record.msg)
    return "[message omitted]"


def _safe_event(record: logging.LogRecord) -> str:
    event = record.__dict__.get("event")
    if type(event) is str and _SUMMARY.fullmatch(event):
        return _redact_text(event)
    return "log"


def _safe_timestamp(created: Any) -> str:
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


def _bounded_json(payload: dict[str, Any], limit: int) -> str:
    candidate = dict(payload)
    encoded = orjson.dumps(candidate)
    if len(encoded) <= limit:
        return encoded.decode("utf-8")

    candidate.pop("message", None)
    encoded = orjson.dumps(candidate)
    if len(encoded) <= limit:
        return encoded.decode("utf-8")

    for field in reversed(_CORRELATION_FIELDS):
        candidate.pop(field, None)
        encoded = orjson.dumps(candidate)
        if len(encoded) <= limit:
            return encoded.decode("utf-8")
    candidate.pop("exception_type", None)
    encoded = orjson.dumps(candidate)
    if len(encoded) <= limit:
        return encoded.decode("utf-8")

    event = candidate.get("event", "log")
    module = candidate.get("module", "logagent")
    level = candidate.get("level", "INFO")
    timestamp = candidate.get("time", "1970-01-01T00:00:00Z")
    for event_bytes in (64, 32, 16, 8):
        candidate["event"] = (
            _truncate_text(event, event_bytes) if type(event) is str else "log"
        )
        candidate["module"] = (
            _truncate_text(module, 16) if type(module) is str else "logagent"
        )
        candidate["level"] = (
            _truncate_text(level, 8) if type(level) is str else "INFO"
        )
        candidate["time"] = (
            _truncate_text(timestamp, 32)
            if type(timestamp) is str
            else "1970-01-01T00:00:00Z"
        )
        encoded = orjson.dumps(candidate)
        if len(encoded) <= limit:
            return encoded.decode("utf-8")

    fallback = {
        "time": _truncate_text(str(timestamp), 24),
        "level": _truncate_text(str(level), 8),
        "module": "log",
        "event": "log",
    }
    encoded = orjson.dumps(fallback)
    if len(encoded) > limit:
        raise ValueError("max_bytes is too small for a bounded JSON log record")
    return encoded.decode("utf-8")


class RedactingJsonFormatter(logging.Formatter):
    """Serialize bounded diagnostic summaries without formatting record arguments."""

    def __init__(self, max_bytes: int = _MAX_BYTES) -> None:
        if type(max_bytes) is not int or max_bytes < _MIN_MAX_BYTES:
            raise ValueError(f"max_bytes must be an integer at least {_MIN_MAX_BYTES}")
        super().__init__()
        self._limit = max_bytes - 1

    def format(self, record: logging.LogRecord) -> str:
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
                payload["exception_type"] = _redact_text(
                    _truncate_text(exception_type, 128)
                )
        return _bounded_json(payload, self._limit)


class _SafeRotatingFileHandler(RotatingFileHandler):
    """Capture write failures locally without writing the original record to stderr."""

    def __init__(
        self,
        *args: Any,
        on_error: Callable[[ErrorInfo], None],
        **kwargs: Any,
    ) -> None:
        self._on_error = on_error
        self._last_error: ErrorInfo | None = None
        super().__init__(*args, **kwargs)

    @property
    def last_error(self) -> ErrorInfo | None:
        error = self._last_error
        return error.model_copy(deep=True) if error is not None else None

    def emit(self, record: logging.LogRecord) -> None:
        self._last_error = None
        super().emit(record)

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        # The stdlib counts characters; our on-disk budget counts UTF-8 bytes.
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        size = self.stream.tell()
        length = len((self.format(record) + self.terminator).encode("utf-8"))
        return size > 0 and size + length > self.maxBytes

    def handleError(self, record: logging.LogRecord) -> None:
        del record
        exc_type = sys.exc_info()[0]
        exception_type = (
            exc_type.__name__
            if exc_type is not None and type(exc_type.__name__) is str
            else "LoggingError"
        )
        error = ErrorInfo(
            code="logging_write_failed",
            message="日志写入失败",
            details={"operation": "emit", "exception_type": exception_type},
        )
        self._last_error = error
        self._on_error(error)


class JsonLogSink:
    """Own one package logger handler so repeated lifecycle creation is deterministic."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int = _MAX_BYTES,
        backup_count: int = _BACKUP_COUNT,
    ) -> None:
        if type(max_bytes) is not int or max_bytes < _MIN_MAX_BYTES:
            raise ValueError(f"max_bytes must be an integer at least {_MIN_MAX_BYTES}")
        if type(backup_count) is not int or backup_count < 1:
            raise ValueError("backup_count must be a positive integer")
        self.path = Path(path).absolute()
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._logger = logging.getLogger(_LOGGER_NAME)
        self._handler: _SafeRotatingFileHandler | None = None
        self._state = "created"
        self._error: ErrorInfo | None = None
        self._lock = threading.RLock()
        self._error_lock = threading.Lock()
        self._previous_level: int | None = None
        self._previous_propagate: bool | None = None

    @property
    def error(self) -> ErrorInfo | None:
        with self._error_lock:
            error = self._error
            return error.model_copy(deep=True) if error is not None else None

    def _set_error(self, error: ErrorInfo | None) -> None:
        with self._error_lock:
            self._error = error.model_copy(deep=True) if error is not None else None

    def _record_error(self, error: ErrorInfo) -> None:
        if self._state == "started" and self._handler is not None:
            self._set_error(error)

    @staticmethod
    def _generic_error(code: str, message: str, exc: Exception) -> ErrorInfo:
        return ErrorInfo(
            code=code,
            message=message,
            details={"exception_type": type(exc).__name__},
        )

    def _conflicting_handler(self) -> logging.Handler | None:
        for handler in self._logger.handlers:
            if getattr(handler, _HANDLER_MARKER, False):
                return handler
        return None

    def start(self) -> None:
        with _OWNERSHIP_LOCK:
            with self._lock:
                if self._state == "started":
                    return
                conflict = self._conflicting_handler()
                if conflict is not None:
                    raise RuntimeError("a lifecycle log sink already owns the logger")

                self._state = "starting"
                self._set_error(None)
                self._previous_level = self._logger.level
                self._previous_propagate = self._logger.propagate
                handler: _SafeRotatingFileHandler | None = None
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    handler = _SafeRotatingFileHandler(
                        self.path,
                        maxBytes=self._max_bytes,
                        backupCount=self._backup_count,
                        encoding="utf-8",
                        on_error=self._record_error,
                    )
                    setattr(handler, _HANDLER_MARKER, True)
                    setattr(handler, _HANDLER_OWNER, id(self))
                    handler.setFormatter(RedactingJsonFormatter(self._max_bytes))
                    self._logger.addHandler(handler)
                    self._logger.setLevel(logging.INFO)
                    self._logger.propagate = False
                except Exception as exc:
                    if handler is not None:
                        self._logger.removeHandler(handler)
                        handler.close()
                    self._handler = None
                    self._previous_level = None
                    self._previous_propagate = None
                    self._state = "failed"
                    self._set_error(
                        self._generic_error("logging_start_failed", "日志 sink 启动失败", exc)
                    )
                    raise RuntimeError("log sink failed to start") from None

                self._handler = handler
                self._state = "started"

    def check(self) -> ErrorInfo | None:
        """Run a local write probe; never logs recursively or performs remote I/O."""
        with self._lock:
            if self._state == "closed":
                self._set_error(
                    ErrorInfo(code="logging_closed", message="日志 sink 已关闭")
                )
                return self.error
            if self._state != "started" or self._handler is None:
                return ErrorInfo(
                    code="logging_not_started",
                    message="日志 sink 尚未启动",
                    details={"state": self._state},
                )

            probe = logging.LogRecord(
                name=self._logger.name,
                level=logging.DEBUG,
                pathname=__file__,
                lineno=0,
                msg="logging_health_check",
                args=(),
                exc_info=None,
            )
            probe.event = "logging_health_check"
            probe.status = "available"
            self._handler.acquire()
            try:
                self._handler.emit(probe)
            finally:
                self._handler.release()
            self._set_error(self._handler.last_error)
            return self.error

    def close(self) -> None:
        with _OWNERSHIP_LOCK:
            with self._lock:
                if self._state == "closed":
                    return
                handler = self._handler
                self._handler = None
                close_error: Exception | None = None
                try:
                    if handler is not None:
                        self._logger.removeHandler(handler)
                        handler.close()
                except Exception as exc:
                    close_error = exc
                finally:
                    if self._previous_level is not None:
                        self._logger.setLevel(self._previous_level)
                    if self._previous_propagate is not None:
                        self._logger.propagate = self._previous_propagate
                    self._previous_level = None
                    self._previous_propagate = None
                    self._state = "closed"
                    if close_error is None:
                        self._set_error(
                            ErrorInfo(code="logging_closed", message="日志 sink 已关闭")
                        )
                    else:
                        self._set_error(
                            self._generic_error(
                                "logging_close_failed", "日志 sink 关闭失败", close_error
                            )
                        )
                if close_error is not None:
                    raise RuntimeError("log sink failed to close") from None
