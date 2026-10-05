"""FastAPI native SSE transport behavior."""

import json

import pytest
from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.testclient import TestClient
from pydantic import ValidationError


def test_native_sse_preserves_event_fields_and_unicode():
    app = FastAPI()

    @app.get("/events", response_class=EventSourceResponse)
    async def events():
        yield ServerSentEvent(data={"text": "告警\n下一行"}, event="snapshot", id="7")

    with TestClient(app) as client:
        response = client.get("/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    lines = response.text.splitlines()
    assert lines[0] == "event: snapshot"
    assert json.loads(lines[1].removeprefix("data: ")) == {"text": "告警\n下一行"}
    assert lines[2] == "id: 7"


@pytest.mark.parametrize("field,value", [
    ("event", "snapshot\ninjected"),
    ("id", "7\rdata: injected"),
    ("id", "7\x00"),
])
def test_sse_rejects_invalid_metadata(field, value):
    with pytest.raises(ValidationError):
        ServerSentEvent(data={}, **{field: value})
