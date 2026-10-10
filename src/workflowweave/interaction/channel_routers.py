"""Web transport projection for the shared Agent command channel."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.sse import EventSourceResponse, ServerSentEvent

from workflowweave.agent.commands import AgentCommand
from workflowweave.channel.web import WebChannel
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.lifecycle import ApplicationServices
from workflowweave.models import ID

from .dependencies import get_services

Services = Annotated[ApplicationServices, Depends(get_services)]
_TERMINAL_TURN_EVENTS = frozenset({
    "turn.completed", "turn.failed", "turn.cancelled", "turn.interrupted",
})


@dataclass(frozen=True, slots=True)
class AgentEventStream:
    channel: WebChannel
    session_id: str
    cursor: int


async def prepare_agent_events(
    session_id: ID,
    services: Services,
    after: int = Query(0, ge=0),
    last_event_id: str | None = Header(None),
) -> AgentEventStream:
    cursor = max(after, int(last_event_id)) if last_event_id and last_event_id.isdigit() else after
    channel = services.channels.web_channel
    await channel.get_session(session_id)
    await channel.events(session_id, after=cursor)
    return AgentEventStream(channel, session_id, cursor)


async def dispatch_web(services: ApplicationServices, command: AgentCommand):
    manager = getattr(services, "channels", None)
    web = getattr(manager, "web_channel", None)
    if web is None:
        raise WorkFLowWeaveError("not_ready", "Agent Web 渠道尚未装配")
    return await web.dispatch(command)


def build_channel_router() -> APIRouter:
    router = APIRouter(prefix="/channels/web")

    @router.post("/commands", status_code=202)
    async def command(
        payload: AgentCommand,
        services: Services,
    ):
        return await dispatch_web(services, payload)

    @router.get("/requests/{request_id}")
    async def outcome(request_id: str, services: Services, session: ID | None = None):
        return await services.channels.web_channel.outcome(request_id, session=session)

    @router.get("/sessions/{session_id}/events", response_class=EventSourceResponse)
    async def events(
        stream: Annotated[AgentEventStream, Depends(prepare_agent_events)],
    ) -> AsyncIterator[ServerSentEvent]:
        async for event in stream_agent_events(stream):
            yield event

    return router


async def stream_agent_events(
    stream: AgentEventStream,
) -> AsyncIterator[ServerSentEvent]:
    cursor = stream.cursor

    async def drain_tail() -> AsyncIterator[ServerSentEvent]:
        nonlocal cursor
        for event in await stream.channel.events(stream.session_id, after=cursor):
            if event["id"] <= cursor:
                continue
            cursor = event["id"]
            yield ServerSentEvent(data=event, id=str(cursor))

    while True:
        batch = await stream.channel.wait_events(stream.session_id, after=cursor, wait_seconds=15.0)
        terminal_seen = False
        for event in batch:
            cursor = event["id"]
            terminal_seen = terminal_seen or event.get("type") in _TERMINAL_TURN_EVENTS
            yield ServerSentEvent(data=event, id=str(cursor))
        if terminal_seen:
            async for event in drain_tail():
                yield event
            break
        # A session may already be terminal when the stream starts, with no
        # terminal event after the requested cursor.  Check that only on an
        # empty heartbeat; normal token batches must not rebuild the complete
        # SessionStore document on every event.
        if not batch:
            session = await stream.channel.get_session(stream.session_id)
            if session["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                async for event in drain_tail():
                    yield event
                break


channel_router = build_channel_router()
router = channel_router
