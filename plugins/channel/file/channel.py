"""Append-only notification logging channel.

The channel uses a dedicated ``logging.FileHandler`` per normalized path.  It
invokes the handler directly, so application logger levels, filters and global
logging switches cannot silently drop a notification.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logagent.channel.errors import ChannelDeliveryError
from logagent.errors import LogAgentError
from logagent.models import ChannelConfig, Notification
from logagent.schema import resource_options_schema, validate_instance

_STOP_TIMEOUT = 5.0
_OPTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "minLength": 1,
            "description": "日志文件（相对 data_dir）",
            "x-logagent-path": True,
        }
    },
    "required": ["path"],
    "additionalProperties": False,
}


class _UTCFormatter(logging.Formatter):
    converter = time.gmtime


class _NotificationFileHandler(logging.FileHandler):
    """A FileHandler whose write/flush failures reach the channel caller."""

    def __init__(self, path: Path):
        super().__init__(path, mode="a", encoding="utf-8", delay=True)
        self.path = path
        # Keep the underlying stream visible for diagnostics and deterministic
        # tests while retaining FileHandler's public ``stream`` attribute.
        self._io_lock = self.lock
        self.setFormatter(
            _UTCFormatter(
                "%(asctime)sZ channel=%(channel_id)s session=%(session_id)s "
                "output=%(output_id)s title=%(title)s\n%(message)s"
            )
        )

    @property
    def _stream(self):
        return self.stream

    @_stream.setter
    def _stream(self, value):
        self.stream = value

    def start(self) -> None:
        with self.lock:
            if self.stream is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.stream = self._open()

    def write_notification(
        self,
        notification: Notification,
        channel_id: str,
        result: _WriteResult,
    ) -> None:
        if self.stream is None:
            raise RuntimeError("file handler is not started")
        record = logging.LogRecord(
            name="logagent.channel.file",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=notification.text,
            args=(),
            exc_info=None,
        )
        record.channel_id = channel_id
        record.session_id = notification.session_id
        record.output_id = notification.output_id
        record.title = notification.title
        record.delivery_result = result
        self.acquire()
        try:
            self.emit(record)
        finally:
            self.release()

    def emit(self, record: logging.LogRecord) -> None:
        result: _WriteResult = record.delivery_result
        try:
            if self.stream is None:
                raise RuntimeError("file handler is not started")
            rendered = self.format(record) + self.terminator
            result.operation = "write"
            result.expected = len(rendered)
            result.started = True
            written = self.stream.write(rendered)
            result.written = written if isinstance(written, int) else None
            if type(written) is not int or written != len(rendered):
                raise OSError(
                    errno.EIO,
                    f"short write: wrote {written} of {len(rendered)} characters",
                )
            result.operation = "flush"
            self.flush()
            result.success = True
        except Exception as exc:
            result.error = exc
            result.uncertain = result.started
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:
        del record
        error = sys.exc_info()[1]
        if error is None:
            raise RuntimeError("file handler error occurred outside an exception")
        raise error

    def close(self) -> None:
        with self.lock:
            super().close()


@dataclass
class _WriteResult:
    started: bool = False
    success: bool = False
    uncertain: bool = False
    operation: str = "write"
    error: BaseException | None = None
    written: int | None = None
    expected: int | None = None


_HANDLERS: dict[str, tuple[_NotificationFileHandler, int]] = {}
_HANDLERS_LOCK = threading.Lock()


class FileChannel:
    def __init__(self, config: ChannelConfig):
        validate_instance(config.options, resource_options_schema(_OPTIONS_SCHEMA), path=["options"])
        self.path = Path(config.options["path"]).resolve()
        self.channel_id = config.id
        self._released = False
        self._pending: set[asyncio.Task] = set()
        self._stop_task: asyncio.Task | None = None
        key = str(self.path.absolute())
        with _HANDLERS_LOCK:
            shared = _HANDLERS.get(key)
            if shared is None:
                self.handler = _NotificationFileHandler(self.path)
                _HANDLERS[key] = (self.handler, 1)
            else:
                self.handler = shared[0]
                _HANDLERS[key] = (self.handler, shared[1] + 1)

    async def _run_io(self, function, *args):
        if self._stop_task is not None:
            raise ChannelDeliveryError("file_closed", "文件渠道已关闭")
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        self._pending.add(task)
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._pending.discard(task)

    async def start(self) -> None:
        await self._run_io(self.handler.start)

    async def send(self, notification: Notification, *, options: dict) -> None:
        if options:
            raise ChannelDeliveryError("invalid_config", "文件渠道没有调用选项")
        result = _WriteResult()

        def write() -> None:
            if self.handler.stream is None:
                raise RuntimeError("file handler is not started")
            try:
                self.handler.write_notification(notification, self.channel_id, result)
            except BaseException as exc:
                result.error = exc
                result.uncertain = result.uncertain or result.started
                raise
            result.success = True

        try:
            await self._run_io(write)
        except asyncio.CancelledError:
            if result.started:
                result.uncertain = True
            raise
        except ChannelDeliveryError:
            raise
        except Exception as exc:
            if result.error is None:
                result.error = exc
            raise self._delivery_error(result) from exc
        if not result.success:
            result.error = RuntimeError("file write did not complete")
            raise self._delivery_error(result)

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._finish())
        try:
            await asyncio.wait_for(asyncio.shield(self._stop_task), _STOP_TIMEOUT)
        except TimeoutError as exc:
            raise LogAgentError("file_stop_timeout", "文件操作尚未结束") from exc

    async def _finish(self) -> None:
        outcomes = await asyncio.gather(*self._pending, return_exceptions=True)
        self._pending.clear()
        failures = [type(value).__name__ for value in outcomes if isinstance(value, BaseException)]
        try:
            await asyncio.to_thread(self._release_handler)
        except Exception as exc:
            failures.append(type(exc).__name__)
        if failures:
            raise LogAgentError("file_cleanup_failed", "文件渠道清理失败", {"failures": failures})

    def _release_handler(self) -> None:
        key = str(self.path.absolute())
        with _HANDLERS_LOCK:
            if self._released:
                return
            self._released = True
            handler, refs = _HANDLERS[key]
            _HANDLERS[key] = (handler, refs - 1)
            if refs > 1:
                return
        with handler.lock:
            with _HANDLERS_LOCK:
                if _HANDLERS[key][1] > 0:
                    return
            try:
                handler.close()
            finally:
                with _HANDLERS_LOCK:
                    if _HANDLERS[key][1] == 0:
                        _HANDLERS.pop(key)

    @staticmethod
    def _delivery_error(result: _WriteResult) -> ChannelDeliveryError:
        error = result.error or RuntimeError("file write did not complete")
        details: dict[str, Any] = {
            "exception_type": type(error).__name__,
            "operation": result.operation,
        }
        if isinstance(error, OSError) and error.errno is not None:
            details["errno"] = error.errno
        if result.written is not None:
            details["written"] = result.written
        if result.expected is not None:
            details["expected"] = result.expected
        return ChannelDeliveryError(
            "file_write_failed",
            f"文件日志写入失败（{result.operation}，{type(error).__name__}）",
            uncertain=result.uncertain,
            details=details,
        )


class FileChannelType:
    name = "file"
    id_prefix = "file"
    description = "将通知追加到 UTF-8 日志文件"
    capabilities = ["notification"]
    options_schema = _OPTIONS_SCHEMA

    async def create(self, config: ChannelConfig, credentials: Any) -> FileChannel:
        return FileChannel(config)
