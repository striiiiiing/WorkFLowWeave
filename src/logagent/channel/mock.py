from __future__ import annotations

import asyncio
import errno
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logagent.channel.errors import ChannelDeliveryError
from logagent.errors import LogAgentError
from logagent.models import ChannelConfig, Notification

_STOP_TIMEOUT = 5.0
_HANDLERS: dict[str, tuple[_FileHandler, int]] = {}
_HANDLERS_LOCK = threading.Lock()


@dataclass
class _WriteResult:
    success: bool = False
    started: bool = False
    uncertain: bool = False
    operation: str | None = None
    error: BaseException | None = None
    written: int | None = None
    expected: int | None = None


class _FileHandler(logging.Handler):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self._stream = None
        self._io_lock = threading.Lock()

    def start(self):
        # The handler is shared by every instance writing to the same file, so a
        # second owner starting it must reuse the open stream instead of
        # replacing (and closing) the stream other sends may be writing to.
        with self._io_lock:
            if self._stream is not None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._stream = self.path.open("a", encoding="utf-8")

    def write(self, title: str, text: str, result: _WriteResult) -> None:
        payload = title + ("\n" if title else "") + text + "\n"
        with self._io_lock:
            if self._stream is None:
                result.operation = "write"
                result.error = RuntimeError("mock handler is not started")
                raise result.error
            result.started = True
            result.operation = "write"
            result.expected = len(payload)
            try:
                written = self._stream.write(payload)
                result.written = written if isinstance(written, int) else None
                if type(written) is not int or written != len(payload):
                    raise OSError(
                        errno.EIO,
                        f"short write: wrote {written} of {len(payload)} characters",
                    )
                result.operation = "flush"
                self._stream.flush()
            except BaseException as exc:
                result.error = exc
                result.uncertain = result.started
                raise
            result.success = True

    def _close_stream(self):
        if self._stream is not None:
            stream = self._stream
            self._stream = None
            stream.close()

    def close(self):
        with self._io_lock:
            self._close_stream()
        super().close()


class MockFileChannel:
    def __init__(self, config: ChannelConfig):
        self.path = Path(config.options["path"])
        self._released = False
        self._pending: set[asyncio.Task] = set()
        self._stop_task: asyncio.Task | None = None
        key = str(self.path)
        with _HANDLERS_LOCK:
            shared = _HANDLERS.get(key)
            if shared is None:
                self.handler = _FileHandler(self.path)
                _HANDLERS[key] = (self.handler, 1)
            else:
                self.handler = shared[0]
                _HANDLERS[key] = (self.handler, shared[1] + 1)

    async def _run_io(self, function, *args):
        if self._stop_task is not None:
            raise ChannelDeliveryError("mock_closed", "Mock 渠道已关闭")
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        self._pending.add(task)
        try:
            return await asyncio.shield(task)
        finally:
            # Cancellation cannot stop a running thread. Keep its ownership until
            # stop has observed completion, including any deferred write failure.
            if task.done():
                self._pending.discard(task)

    async def start(self) -> None:
        await self._run_io(self.handler.start)

    async def send(self, notification: Notification, *, options: dict) -> None:
        if options:
            raise ChannelDeliveryError("invalid_config", "Mock 渠道没有调用选项")
        result = _WriteResult()
        try:
            await self._run_io(
                self.handler.write,
                notification.title,
                notification.text,
                result,
            )
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
            result.error = RuntimeError("mock handler did not complete the write")
            raise self._delivery_error(result)

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._finish())
        try:
            await asyncio.wait_for(asyncio.shield(self._stop_task), _STOP_TIMEOUT)
        except TimeoutError as exc:
            # The owned cleanup task remains available to a later stop call.
            raise LogAgentError("mock_stop_timeout", "Mock 文件操作尚未结束") from exc

    async def _finish(self) -> None:
        outcomes = await asyncio.gather(*self._pending, return_exceptions=True)
        self._pending.clear()
        failures = [type(value).__name__ for value in outcomes if isinstance(value, BaseException)]
        try:
            await asyncio.to_thread(self._release_handler)
        except Exception as exc:
            failures.append(type(exc).__name__)
        if failures:
            raise LogAgentError("mock_cleanup_failed", "Mock 文件清理失败", {"failures": failures})

    def _release_handler(self) -> None:
        key = str(self.path)
        with _HANDLERS_LOCK:
            if self._released:
                return
            self._released = True
            handler, refs = _HANDLERS[key]
            _HANDLERS[key] = (handler, refs - 1)
            if refs > 1:
                return
        # Keep the pool entry while close runs. A new owner reuses this same
        # I/O lock, so it cannot open a competing handler during final flush.
        with handler._io_lock:
            with _HANDLERS_LOCK:
                if _HANDLERS[key][1] > 0:
                    return
            try:
                handler._close_stream()
            finally:
                with _HANDLERS_LOCK:
                    if _HANDLERS[key][1] == 0:
                        _HANDLERS.pop(key)

    @staticmethod
    def _delivery_error(result: _WriteResult) -> ChannelDeliveryError:
        error = result.error or RuntimeError("mock write did not complete")
        operation = result.operation or "write"
        details: dict[str, Any] = {
            "exception_type": type(error).__name__,
            "operation": operation,
        }
        if isinstance(error, OSError) and error.errno is not None:
            details["errno"] = error.errno
        if result.written is not None:
            details["written"] = result.written
        if result.expected is not None:
            details["expected"] = result.expected
        return ChannelDeliveryError(
            "mock_write_failed",
            f"Mock 文件写入失败（{operation}，{type(error).__name__}）",
            uncertain=result.uncertain,
            details=details,
        )


class MockFileChannelType:
    name = "mock"
    description = "将通知以可读文本追加到文件"
    capabilities = ["notification"]
    options_schema = {"type": "object", "properties": {"path": {"type": "string", "minLength": 1, "description": "输出文件（相对 data_dir）", "x-logagent-path": True}}, "required": ["path"], "additionalProperties": False}

    async def create(self, config: ChannelConfig, credentials: Any) -> MockFileChannel:
        return MockFileChannel(config)
