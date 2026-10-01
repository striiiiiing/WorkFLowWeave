"""Shared completion flow for Agent conversation transports."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    status: str
    text: str


class BaseConversationChannel:
    """Wait for Agent facts without owning an Agent turn or a transport task."""

    def __init__(self, process_port: Any):
        self._port = process_port

    async def finish_turn(self, turn_id: str) -> ProcessOutcome:
        try:
            result = await self._port.wait(turn_id)
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            return ProcessOutcome("interrupted", "本轮已停止。")
        except Exception as exc:
            logger.exception("channel_turn_failed")
            return ProcessOutcome("failed", f"Agent 执行失败：{getattr(exc, 'code', type(exc).__name__)}")
        status = "interrupted" if result["status"] == "cancelled" else result["status"]
        return ProcessOutcome(status, result.get("text") or f"轮次状态：{result['status']}")

    async def finish_command(self, session_id: str, *, request_id: str | None = None,
                             event_id: int | None = None) -> ProcessOutcome:
        event = await self._port.wait_command(
            session_id, request_id=request_id, event_id=event_id,
        )
        status = "completed" if event["type"] == "command.completed" else (
            "interrupted" if event["type"] == "command.cancelled" else "failed"
        )
        return ProcessOutcome(status, f"命令状态：{status}")
