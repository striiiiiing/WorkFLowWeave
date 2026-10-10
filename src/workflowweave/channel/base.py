"""Shared completion flow for Agent conversation transports."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from workflowweave.models import ErrorInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    status: str
    text: str


class BaseConversationChannel:
    """Wait for Agent facts without owning an Agent turn or a transport task."""

    def __init__(self, process_port: Any):
        self._port = process_port

    async def finish_turn(self, turn_id: str, *, operation: str = "message") -> ProcessOutcome:
        label = "上下文整理" if operation == "compact" else "Agent 执行"
        try:
            result = await self._port.wait(turn_id)
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            text = "上下文整理已停止。" if operation == "compact" else "本轮已停止。"
            return ProcessOutcome("interrupted", text)
        except Exception as exc:
            logger.exception("channel_turn_failed")
            error = getattr(exc, "info", None) or getattr(exc, "report", None)
            public_error = error.model_dump() if isinstance(error, ErrorInfo) else {"type": type(exc).__name__}
            return ProcessOutcome("failed", self._failure_text(label, public_error))
        status = "interrupted" if result["status"] == "cancelled" else result["status"]
        if status == "failed":
            return ProcessOutcome(status, self._failure_text(label, result.get("error")))
        if status == "interrupted":
            text = "上下文整理已停止。" if operation == "compact" else "本轮已停止。"
            return ProcessOutcome(status, text)
        if operation == "compact" and status == "completed":
            return ProcessOutcome(status, "上下文整理已完成。")
        return ProcessOutcome(status, result.get("text") or f"轮次状态：{result['status']}")

    async def finish_command(self, session_id: str, *, request_id: str | None = None,
                             event_id: int | None = None) -> ProcessOutcome:
        event = await self._port.wait_command(
            session_id, request_id=request_id, event_id=event_id,
        )
        status = "completed" if event["type"] == "command.completed" else (
            "interrupted" if event["type"] == "command.cancelled" else "failed"
        )
        command = event["command"]
        label = "上下文整理" if command == "compact" else "补充内容处理"
        if status == "failed":
            return ProcessOutcome(status, self._failure_text(label, event.get("error")))
        if status == "interrupted":
            return ProcessOutcome(status, f"{label}已取消，未生效。")
        if command == "compact":
            text = "上下文已压缩。" if event["compacted"] else "当前上下文无需压缩。"
        else:
            text = "补充内容已加入当前轮次。"
        return ProcessOutcome(status, text)

    @staticmethod
    def _failure_text(label: str, error: dict | None) -> str:
        if error is None:
            return f"{label}失败。"
        if "code" in error:
            return f"{label}失败：{error['code']}：{error['message']}"
        # Unstructured runtime errors may contain credentials or input dumps.
        return f"{label}失败：{error['type']}"
