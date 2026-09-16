from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from logagent.models import ChannelConfig, Notification


class MockFileChannel:
    def __init__(self, config: ChannelConfig):
        self.path = Path(config.options["path"])

    async def start(self) -> None:
        await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)

    async def send(self, notification: Notification) -> None:
        payload = json.dumps(notification.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")) + "\n"
        def write() -> None:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
        await asyncio.to_thread(write)

    async def stop(self) -> None:
        return None


class MockFileChannelType:
    name = "mock"
    description = "追加 JSON Lines 通知"
    capabilities = ["notification"]
    options_schema = {"type": "object", "properties": {"path": {"type": "string", "minLength": 1, "description": "输出文件（相对 data_dir）", "x-logagent-path": True}}, "required": ["path"], "additionalProperties": False}

    async def create(self, config: ChannelConfig, credentials: Any) -> MockFileChannel:
        return MockFileChannel(config)
