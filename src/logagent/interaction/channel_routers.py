"""Web transport projection for the shared Agent command channel."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from logagent.channel.agent import AgentCommand
from logagent.channel.web import WebChannel
from logagent.errors import LogAgentError
from logagent.lifecycle import ApplicationServices
from logagent.models import ID

from .dependencies import get_services
from .sse import HEARTBEAT, SSEItem, SSEMessage, sse_response

Services = Annotated[ApplicationServices, Depends(get_services)]


async def dispatch_web(services: ApplicationServices, command: AgentCommand):
    manager = getattr(services, "channels", None)
    web = getattr(manager, "web_channel", None)
    if web is None:
        raise LogAgentError("not_ready", "Agent Web 渠道尚未装配")
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

    @router.get("/sessions/{session_id}/events")
    async def events(
        session_id: ID,
        services: Services,
        after: int = Query(0, ge=0),
        last_event_id: str | None = Header(None),
    ):
        return await stream_agent_events(
            services.channels.web_channel, session_id,
            after=after, last_event_id=last_event_id,
        )

    return router


async def stream_agent_events(
    channel: WebChannel,
    session_id: str,
    *,
    after: int = 0,
    last_event_id: str | None = None,
) -> StreamingResponse:
    cursor = max(after, int(last_event_id)) if last_event_id and last_event_id.isdigit() else after
    await channel.get_session(session_id)
    await channel.events(session_id, after=cursor)

    async def stream() -> AsyncIterator[SSEItem]:
        nonlocal cursor
        while True:
            batch = await channel.wait_events(session_id, after=cursor, wait_seconds=0.5)
            for event in batch:
                cursor = event["id"]
                yield SSEMessage(data=event, id=str(cursor))
            session = await channel.get_session(session_id)
            if session["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                for event in await channel.events(session_id, after=cursor):
                    if event["id"] > cursor:
                        cursor = event["id"]
                        yield SSEMessage(data=event, id=str(cursor))
                break
            yield HEARTBEAT

    return sse_response(stream())


channel_router = build_channel_router()
router = channel_router
