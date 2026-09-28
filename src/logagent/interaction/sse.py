"""Shared HTTP framing and response lifecycle for server-sent events."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SSEMessage:
    data: Any
    event: str | None = None
    id: str | None = None


@dataclass(frozen=True)
class SSEHeartbeat:
    pass


HEARTBEAT = SSEHeartbeat()
SSEItem = SSEMessage | SSEHeartbeat


def _metadata(field: str, value: str) -> str:
    if not value or any(char in value for char in "\r\n\x00"):
        raise ValueError(f"invalid SSE {field}")
    return f"{field}: {value}\n"


def encode_sse(item: SSEItem) -> str:
    if isinstance(item, SSEHeartbeat):
        return ": heartbeat\n\n"
    if not isinstance(item, SSEMessage):
        raise TypeError("expected SSEMessage or SSEHeartbeat")
    fields = []
    if item.event is not None:
        fields.append(_metadata("event", item.event))
    if item.id is not None:
        fields.append(_metadata("id", item.id))
    fields.append(f"data: {json.dumps(item.data, ensure_ascii=False, allow_nan=False)}\n")
    return "".join(fields) + "\n"


def sse_response(source: AsyncGenerator[SSEItem, None]) -> StreamingResponse:
    async def stream() -> AsyncGenerator[str, None]:
        try:
            async for item in source:
                yield encode_sse(item)
        except Exception:
            logger.exception("SSE stream failed")
            raise
        finally:
            await source.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
