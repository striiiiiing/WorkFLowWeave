"""管理应用日志 handler 的独占所有权、按字节轮转和脱敏写入诊断。"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from workflowweave.models import ErrorInfo

from .formatting import _MAX_BYTES, _MIN_MAX_BYTES, RedactingJsonFormatter

_BACKUP_COUNT = 5
_HANDLER_MARKER = "_workflowweave_lifecycle_handler"
_LOGGER_NAME = "workflowweave"
_OWNERSHIP_LOCK = threading.RLock()


class _SafeRotatingFileHandler(RotatingFileHandler):
    """本地记录写入失败，避免标准错误处理将原始日志输出到 stderr。"""

    def __init__(
        self,
        *args: Any,
        on_error: Callable[[ErrorInfo], None],
        **kwargs: Any,
    ) -> None:
        """注册脱敏错误回调，其余文件与轮转参数交给标准库初始化。"""
        self._on_error = on_error
        self._last_error: ErrorInfo | None = None
        super().__init__(*args, **kwargs)

    @property
    def last_error(self) -> ErrorInfo | None:
        """返回最近一次写入诊断的深拷贝，成功写入后为 None。"""
        error = self._last_error
        return error.model_copy(deep=True) if error is not None else None

    def emit(self, record: logging.LogRecord) -> None:
        """开始新的写入尝试，清除上次诊断并由 handleError 捕获本次失败。"""
        self._last_error = None
        super().emit(record)

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        """按包含行结束符的 UTF-8 字节数判断轮转，避免标准库字符计数低估大小。"""
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        size = self.stream.tell()
        length = len((self.format(record) + self.terminator).encode("utf-8"))
        return size > 0 and size + length > self.maxBytes

    def handleError(self, record: logging.LogRecord) -> None:
        """保存异常类型并通知 sink，不转储原始记录、异常正文或堆栈。"""
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
    """独占一个应用日志 handler，并在关闭时恢复 logger 原配置。

    所有权锁协调多个 sink，实例锁保护启停和探测，独立错误锁保护诊断快照。
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int = _MAX_BYTES,
        backup_count: int = _BACKUP_COUNT,
    ) -> None:
        """校验轮转字节上限和备份数量，文件与目录推迟到 start 创建。"""
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
        """在线程锁内读取诊断深拷贝，避免调用方修改 sink 状态。"""
        with self._error_lock:
            error = self._error
            return error.model_copy(deep=True) if error is not None else None

    def _set_error(self, error: ErrorInfo | None) -> None:
        """以深拷贝替换诊断快照，None 表示清除当前错误。"""
        with self._error_lock:
            self._error = error.model_copy(deep=True) if error is not None else None

    def _record_error(self, error: ErrorInfo) -> None:
        """仅在 sink 正式持有 handler 时接收其写入错误。"""
        if self._state == "started" and self._handler is not None:
            self._set_error(error)

    @staticmethod
    def _generic_error(code: str, message: str, exc: Exception) -> ErrorInfo:
        """用固定消息和异常类型构造诊断，省略原始异常内容。"""
        return ErrorInfo(
            code=code,
            message=message,
            details={"exception_type": type(exc).__name__},
        )

    def _conflicting_handler(self) -> logging.Handler | None:
        """查找已带生命周期所有权标记的 handler，供持锁启动时检查冲突。"""
        for handler in self._logger.handlers:
            if getattr(handler, _HANDLER_MARKER, False):
                return handler
        return None

    def start(self) -> None:
        """创建日志文件并取得 handler 所有权，启用 INFO 且关闭向父 logger 传播。

        已启动时无副作用，关闭后允许重新启动；另一生命周期 sink 已占用时显式失败。
        """
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
        """直接向 handler 写入本地探测记录，返回诊断或表示成功的 None。

        绕过 logger 避免递归，不执行远程 I/O；成功探测会清除之前的写入错误。
        """
        with self._lock:
            if self._state == "closed":
                self._set_error(ErrorInfo(code="logging_closed", message="日志 sink 已关闭"))
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
        """移除并关闭 handler，恢复原日志级别与传播设置；重复关闭无副作用。

        关闭失败仍恢复 logger 配置并记录诊断，同时抛出脱敏后的 RuntimeError。
        """
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
