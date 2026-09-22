"""HTTP/SSE projection for the independent Agent runtime."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import Field

from logagent.agent.config import AgentConfig as AgentRuntimeConfig
from logagent.agent.workspace import RuntimeIdentity
from logagent.errors import LogAgentError
from logagent.lifecycle import ApplicationServices
from logagent.models import ID, StrictModel

from .dependencies import get_services

Services = Annotated[ApplicationServices, Depends(get_services)]


class AgentSessionCreate(StrictModel):
    model: str | None = None
    workflow_session_id: ID | None = None
    workflow_result: object | None = None


class AgentMessage(StrictModel):
    request_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class AgentFileWrite(StrictModel):
    mode: str
    content: str
    old_text: str | None = None
    expected_hash: str | None = None


def _workspace(service, session_id: str):
    session = service.sessions.get(session_id)
    if session is None:
        raise LogAgentError("session_not_found", "Agent session 不存在")
    identity = RuntimeIdentity(
        session.session_id, session.turn_id or "management", session.branch_id,
        workflow_session_id=session.workflow_session_id, model=session.model,
        workspace=str(service.workspace.root),
    )
    return service.workspace.for_identity(identity)


def _agent(services):
    agent = getattr(services, "agent", None)
    if agent is None:
        raise LogAgentError("not_ready", "Agent 服务尚未装配")
    return agent


def build_agent_router():
    router = APIRouter(prefix="/agents")

    @router.get("/sessions")
    async def list_agent_sessions(services: Services):
        return await _agent(services).list_sessions()

    @router.post("/sessions", status_code=status.HTTP_201_CREATED)
    async def create_agent_session(payload: AgentSessionCreate, services: Services):
        return await _agent(services).create_session(
            model=payload.model,
            workflow_session_id=payload.workflow_session_id,
            workflow_result=payload.workflow_result,
        )

    @router.get("/sessions/{session_id}")
    async def get_agent_session(session_id: ID, services: Services):
        return await _agent(services).get_session(session_id)

    @router.post("/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
    async def send_agent_message(session_id: ID, payload: AgentMessage, services: Services, response: Response):
        accepted = await _agent(services).submit(session_id, payload.text, request_id=payload.request_id)
        response.headers["Location"] = f"/api/agents/sessions/{session_id}/events"
        return accepted

    @router.post("/sessions/{session_id}/cancel")
    async def cancel_agent_session(session_id: ID, services: Services):
        return await _agent(services).cancel(session_id)

    @router.post("/sessions/{session_id}/compact", status_code=status.HTTP_202_ACCEPTED)
    async def compact_agent_session(session_id: ID, services: Services):
        return await _agent(services).compact(session_id)

    @router.get("/sessions/{session_id}/events")
    async def agent_events(session_id: ID, request: Request,
                           services: Services, after: int = Query(0, ge=0),
                           last_event_id: str | None = Header(None)):
        service = _agent(services)
        cursor = after
        if last_event_id is not None and last_event_id.isdigit():
            cursor = max(cursor, int(last_event_id))

        # Validate the session and event file before returning a streaming
        # response.  Exceptions raised after StreamingResponse has sent its
        # headers cannot be represented by the application's structured error
        # handler, which would otherwise turn a missing session into a broken
        # SSE connection with no actionable error body.
        await service.get_session(session_id)
        await service.events(session_id, after=cursor)

        async def stream() -> AsyncIterator[str]:
            nonlocal cursor
            while True:
                events = await service.events(session_id, after=cursor)
                for event in events:
                    cursor = event["id"]
                    yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                session = await service.get_session(session_id)
                if session["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                    break
                if await request.is_disconnected():
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/sessions/{session_id}/files")
    async def read_agent_file(session_id: ID, path: str, services: Services):
        service = _agent(services)
        return await _workspace(service, session_id).read(
            path, sandbox=True, default_limit=service.config.read_lines,
            output_bytes=service.config.output_bytes,
        )

    @router.put("/sessions/{session_id}/files")
    async def write_agent_file(session_id: ID, path: str, payload: AgentFileWrite,
                               services: Services, response: Response,
                               if_match: str | None = Header(None)):
        service = _agent(services)
        workspace = _workspace(service, session_id)
        expected = payload.expected_hash if payload.expected_hash is not None else if_match
        async with service.scheduler.acquire("exclusive"):
            result = await workspace.write(path, payload.mode, payload.content,
                                           old_text=payload.old_text,
                                           expected_hash=expected, sandbox=True)
        if isinstance(result, dict) and isinstance(result.get("hash"), str):
            response.headers["ETag"] = result["hash"]
        return result

    @router.get("/files")
    async def list_agent_files(session_id: ID, services: Services,
                               path: str = Query("."), offset: int = Query(0, ge=0),
                               limit: int | None = Query(None, ge=1)):
        service = _agent(services)
        return await _workspace(service, session_id).read(
            path, offset=offset, limit=limit, sandbox=True,
            default_limit=service.config.read_lines, output_bytes=service.config.output_bytes,
        )

    @router.get("/file")
    async def read_agent_file_projection(session_id: ID, path: str, services: Services,
                                         offset: int = Query(0, ge=0),
                                         limit: int | None = Query(None, ge=1)):
        service = _agent(services)
        return await _workspace(service, session_id).read(
            path, offset=offset, limit=limit, sandbox=True,
            default_limit=service.config.read_lines, output_bytes=service.config.output_bytes,
        )

    @router.put("/file")
    async def write_agent_file_projection(session_id: ID, path: str, payload: AgentFileWrite,
                                          services: Services, response: Response,
                                          if_match: str | None = Header(None)):
        service = _agent(services)
        workspace = _workspace(service, session_id)
        expected = payload.expected_hash if payload.expected_hash is not None else if_match
        async with service.scheduler.acquire("exclusive"):
            result = await workspace.write(path, payload.mode, payload.content,
                                           old_text=payload.old_text,
                                           expected_hash=expected, sandbox=True)
        if isinstance(result, dict) and isinstance(result.get("hash"), str):
            response.headers["ETag"] = result["hash"]
        return result

    @router.get("/config")
    async def get_agent_config(services: Services):
        service = _agent(services)
        sandbox = getattr(service.config, "sandbox", None)
        sandbox_enabled = bool(getattr(sandbox, "enabled", False))
        sandbox_available = shutil.which("bwrap") is not None
        return {"config": service.config.model_dump(mode="json"),
                "tools": service.tool_views(),
                "scheduler": service.scheduler.status,
                "sandbox": {
                    "enabled": sandbox_enabled,
                    "network": bool(getattr(sandbox, "network", False)),
                    "available": sandbox_available,
                    "status": (
                        "enabled" if sandbox_enabled and sandbox_available
                        else "unavailable" if sandbox_enabled
                        else "disabled"
                    ),
                }}

    @router.put("/config")
    async def update_agent_config(payload: AgentRuntimeConfig, services: Services):
        return _agent(services).update_config(payload)

    @router.get("/tools")
    async def list_agent_tools(services: Services):
        return _agent(services).tool_views()

    return router


agent_router = build_agent_router()
