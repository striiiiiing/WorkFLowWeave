from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from logagent.models import ChannelConfig, Notification

_HANDLERS: dict[str, tuple[_FileHandler, int]] = {}
_HANDLERS_LOCK = threading.Lock()


class _FileHandler(logging.Handler):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self._stream = None
        self._io_lock = threading.Lock()

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a", encoding="utf-8")

    def emit(self, record):
        if self._stream is None:
            raise RuntimeError("mock handler is not started")
        with self._io_lock:
            self._stream.write(record.getMessage())
            self._stream.write("\n")
            self._stream.flush()

    def close(self):
        with self._io_lock:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        super().close()


class MockFileChannel:
    def __init__(self, config: ChannelConfig):
        self.path = Path(config.options["path"])
        key = str(self.path)
        with _HANDLERS_LOCK:
            shared = _HANDLERS.get(key)
            if shared is None:
                self.handler = _FileHandler(self.path)
                _HANDLERS[key] = (self.handler, 1)
            else:
                self.handler = shared[0]
                _HANDLERS[key] = (self.handler, shared[1] + 1)

    async def start(self) -> None:
        await asyncio.to_thread(self.handler.start)

    async def send(self, notification: Notification) -> None:
        payload = notification.title + ("\n" if notification.title else "") + notification.text
        record = logging.LogRecord("logagent.mock", logging.INFO, __file__, 0, payload, (), None)
        await asyncio.to_thread(self.handler.handle, record)

    async def stop(self) -> None:
        def release():
            with _HANDLERS_LOCK:
                current = _HANDLERS.get(str(self.path))
                if current is None:
                    return
                handler, refs = current
                if refs > 1:
                    _HANDLERS[str(self.path)] = (handler, refs - 1)
                else:
                    _HANDLERS.pop(str(self.path), None)
                    handler.close()
        await asyncio.to_thread(release)


class MockFileChannelType:
    name = "mock"
    description = "追加 JSON Lines 通知"
    capabilities = ["notification"]
    options_schema = {"type": "object", "properties": {"path": {"type": "string", "minLength": 1, "description": "输出文件（相对 data_dir）", "x-logagent-path": True}}, "required": ["path"], "additionalProperties": False}

    async def create(self, config: ChannelConfig, credentials: Any) -> MockFileChannel:
        return MockFileChannel(config)
