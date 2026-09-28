"""Shared SSE framing and iterator lifecycle."""

import asyncio
import json

import pytest

from logagent.interaction.sse import HEARTBEAT, SSEMessage, encode_sse, sse_response


def test_sse_frame_preserves_unicode_and_escapes_data_newlines():
    frame = encode_sse(SSEMessage(data={"text": "告警\n下一行"}, event="snapshot", id="7"))

    assert frame.startswith("event: snapshot\nid: 7\ndata: ")
    assert json.loads(frame.split("data: ", 1)[1].strip()) == {"text": "告警\n下一行"}
    assert frame.count("\ndata: ") == 1
    assert encode_sse(SSEMessage(data={"id": 8})) == 'data: {"id": 8}\n\n'
    assert encode_sse(HEARTBEAT) == ": heartbeat\n\n"


@pytest.mark.parametrize("field,value", [
    ("event", "snapshot\ninjected"),
    ("event", ""),
    ("id", "7\rdata: injected"),
    ("id", "7\x00"),
])
def test_sse_rejects_invalid_metadata(field, value):
    with pytest.raises(ValueError, match=f"invalid SSE {field}"):
        encode_sse(SSEMessage(data={}, **{field: value}))


async def test_sse_response_closes_source_on_completion_and_encoding_error():
    closed = []

    async def source(data):
        try:
            yield SSEMessage(data=data)
        finally:
            closed.append(data)

    response = sse_response(source({"ok": True}))
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert [chunk async for chunk in response.body_iterator] == ['data: {"ok": true}\n\n']
    assert closed == [{"ok": True}]

    response = sse_response(source({"bad": float("nan")}))
    with pytest.raises(ValueError, match="Out of range float"):
        await anext(response.body_iterator)
    assert len(closed) == 2


async def test_sse_response_closes_source_on_cancellation():
    waiting = asyncio.Event()
    closed = asyncio.Event()

    async def source():
        try:
            yield HEARTBEAT
            waiting.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    response = sse_response(source())
    assert await anext(response.body_iterator) == ": heartbeat\n\n"
    pending = asyncio.create_task(anext(response.body_iterator))
    await asyncio.wait_for(waiting.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.wait_for(closed.wait(), 1)
