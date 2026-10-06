"""Shared native FastAPI SSE types."""

from __future__ import annotations

from fastapi.sse import ServerSentEvent

SSEMessage = ServerSentEvent

__all__ = ["SSEMessage", "ServerSentEvent"]
