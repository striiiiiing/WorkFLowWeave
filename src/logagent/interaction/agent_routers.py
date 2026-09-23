"""HTTP/SSE projection for the independent Agent runtime."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import Field

from logagent.agent.config import AgentConfig as AgentRuntimeConfig
from logagent.agent.workspace import RuntimeIdentity
from logagent.errors import LogAgentError
from logagent.lifecycle import ApplicationServices
from logagent.models import ID, StrictModel

from .dependencies import Lifecycle as LifecycleProtocol
from .dependencies import get_lifecycle, get_services

Services = Annotated[ApplicationServices, Depends(get_services)]
Lifecycle = Annotated[LifecycleProtocol, Depends(get_lifecycle)]


class AgentSessionCreate(StrictModel):
    model: str | None = None
    workflow_session_id: ID | None = None
    workflow_result: object | None = None
    workflow_id: ID | None = None


class AgentMessage(StrictModel):
    request_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class AgentCommand(AgentMessage):
    channel: ID = "web"
    session: ID | None = None
    priority: Literal["stop", "command", "conversation"] | None = None
    model: str | None = None


class AgentForkRequest(StrictModel):
    turn_id: ID | None = None
    model: str | None = None
    message_id: ID | None = None


class AgentFileWrite(StrictModel):
    mode: Literal["overwrite", "append", "replace"]
    content: str
    old_text: str | None = None
    expected_hash: str | None = None


class AgentModelSetting(StrictModel):
    model: str = Field(min_length=1)


class AgentToolSetting(StrictModel):
    enabled: bool


def _workspace(service, session_id: str):
    session = service.sessions.get(session_id)
    if session is None:
        raise LogAgentError("session_not_found", "Agent session 不存在")
    resources = service._session_view(session).get("active_resources") or {}
    identity = RuntimeIdentity(
        session.session_id, session.turn_id or "management", session.branch_id,
        workflow_session_id=session.workflow_session_id,
        model=resources.get("model", session.model) if session.status == "running" else session.model,
        tools_generation=resources.get("tools_generation"),
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
        source_id, result = payload.workflow_session_id, payload.workflow_result
        if payload.workflow_id is not None:
            records = await services.session_view.list_sessions(workflow_id=payload.workflow_id, limit=1000)
            finished = [record for record in records if record.status in {"completed", "partial"}]
            if not finished:
                raise LogAgentError("workflow_result_unavailable", "Workflow 没有可继续的结果")
            source_id = max(finished, key=lambda record: record.finished_at or record.updated_at).session_id
        if source_id is not None:
            if payload.workflow_result is not None:
                raise LogAgentError("invalid_argument", "绑定 Workflow 时由服务读取原始结果，不接受覆盖")
            record = await services.session_view.get_session(source_id)
            if record.status not in {"completed", "partial"}:
                raise LogAgentError("workflow_result_unavailable", "Workflow 运行尚无最终结果")
            phase = await services.session_view.get_phase_content(source_id, "aggregate", version=record.version)
            if phase.availability != "available" or phase.content is None:
                raise LogAgentError("workflow_result_unavailable", "Workflow 最终结果正文不可用")
            result = {"outputs": phase.content.get("outputs", {}),
                      "aggregate": phase.content.get("aggregate"),
                      "workflow_id": record.workflow_id,
                      "finished_at": (record.finished_at or record.updated_at).isoformat()}
        return await _agent(services).create_session(model=payload.model,
                    workflow_session_id=source_id, workflow_result=result)

    @router.post("/commands", status_code=status.HTTP_202_ACCEPTED)
    async def agent_command(payload: AgentCommand, services: Services):
        """Project transport commands onto the same service admission boundary.

        Channel is an origin label, never a tool-selected delivery destination.
        Stop calls cancellation directly, without waiting on message admission.
        """
        service = _agent(services)
        head, _, argument = payload.text.strip().partition(" ")
        priority = "stop" if head == "/stop" else "command" if head.startswith("/") else "conversation"
        if payload.priority is not None and payload.priority != priority:
            raise LogAgentError("invalid_argument", "priority 与命令类别不一致")
        if head == "/new":
            result, kind = await service.create_session(model=payload.model), "session"
        elif head == "/resume":
            result, kind = await service.get_session(argument or payload.session), "session"
        elif head == "/workflow":
            if argument:
                result = await create_agent_session(
                    AgentSessionCreate(workflow_session_id=argument, model=payload.model), services,
                )
                kind = "session"
            else:
                result = await services.session_view.list_sessions(limit=100)
                kind = "workflows"
        else:
            if payload.session is None:
                raise LogAgentError("invalid_argument", "此命令需要 session")
            kind = "turn"
            if head == "/stop":
                result, kind = await service.cancel(payload.session), "session"
            elif head == "/compact":
                result = await service.compact(payload.session)
            elif head == "/append":
                result = await service.append(payload.session, argument, request_id=payload.request_id)
            elif head == "/fork":
                result, kind = await service.fork(payload.session, turn_id=argument or None), "session"
            elif head.startswith("/"):
                raise LogAgentError("invalid_argument", "未知 Agent 命令")
            else:
                result = await service.submit(payload.session, payload.text, request_id=payload.request_id)
        return {"channel": payload.channel, "session": payload.session,
                "priority": priority, "kind": kind, "result": result}

    @router.get("/sessions/{session_id}")
    async def get_agent_session(session_id: ID, services: Services):
        return await _agent(services).get_session(session_id)

    @router.post("/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
    async def send_agent_message(session_id: ID, payload: AgentMessage, services: Services, response: Response):
        accepted = await _agent(services).submit(session_id, payload.text, request_id=payload.request_id)
        response.headers["Location"] = f"/api/agents/sessions/{session_id}/events"
        return accepted

    @router.post("/sessions/{session_id}/append", status_code=status.HTTP_202_ACCEPTED)
    async def append_agent_message(session_id: ID, payload: AgentMessage,
                                   services: Services, response: Response):
        accepted = await _agent(services).append(
            session_id, payload.text, request_id=payload.request_id,
        )
        response.headers["Location"] = f"/api/agents/sessions/{session_id}/events"
        return accepted

    @router.post("/sessions/{session_id}/fork", status_code=status.HTTP_201_CREATED)
    async def fork_agent_session(session_id: ID, payload: AgentForkRequest,
                                 services: Services):
        return await _agent(services).fork(
            session_id, turn_id=payload.turn_id, model=payload.model, message_id=payload.message_id,
        )

    @router.get("/sessions/{session_id}/history")
    async def agent_history(session_id: ID, services: Services):
        return await _agent(services).history(session_id)

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
                log = getattr(service, "sessions", {}).get(session_id)
                if log is not None and getattr(log, "log", None) is not None:
                    events = await log.log.wait_for_events(cursor, wait_seconds=0.5)
                else:
                    # Keep fake/embedded Agent implementations compatible with
                    # the public service protocol; their events() method is the
                    # only available replay source.
                    events = await service.events(session_id, after=cursor)
                    if not events:
                        await asyncio.sleep(0.5)
                for event in events:
                    cursor = event["id"]
                    yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                session = await service.get_session(session_id)
                if session["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                    # A terminal event may commit while this client is yielding
                    # an older batch. Drain that same durable cursor before EOF.
                    for event in await service.events(session_id, after=cursor):
                        if event["id"] > cursor:
                            cursor = event["id"]
                            yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    break
                if await request.is_disconnected():
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @router.get("/sessions/{session_id}/files")
    @router.get("/files")
    @router.get("/file")
    async def read_agent_file(session_id: ID, services: Services, response: Response,
                              path: str = Query("."), offset: int = Query(0, ge=0),
                              limit: int | None = Query(None, ge=1)):
        service = _agent(services)
        async with service.scheduler.acquire("read"):
            result = await _workspace(service, session_id).read(
                path, offset=offset, limit=limit, sandbox=True,
                default_limit=service.config.read_lines, output_bytes=service.config.output_bytes,
            )
        if "hash" in result:
            response.headers["ETag"] = f'"{result["hash"]}"'
        return result

    @router.put("/sessions/{session_id}/files")
    @router.put("/file")
    async def write_agent_file(session_id: ID, path: str, payload: AgentFileWrite,
                               services: Services, response: Response,
                               if_match: str | None = Header(None),
                               if_none_match: str | None = Header(None)):
        if if_match is None and if_none_match != "*":
            raise LogAgentError("precondition_required", "保存必须携带 If-Match；新文件使用 If-None-Match: *")
        if if_match is not None and (if_match == "*" or if_match.startswith("W/") or if_none_match):
            raise LogAgentError("invalid_argument", "保存需要读取所得的强版本号")
        expected = if_match.strip('"') if if_match is not None else "*"
        if payload.expected_hash is not None and payload.expected_hash != expected:
            raise LogAgentError("invalid_argument", "正文版本号与 If-Match 不一致")
        service = _agent(services)
        async with service.scheduler.acquire("exclusive"):
            result = await _workspace(service, session_id).write(
                path, payload.mode, payload.content, old_text=payload.old_text,
                expected_hash=expected, sandbox=True,
            )
        response.headers["ETag"] = f'"{result["hash"]}"'
        await service.sessions[session_id].log.append("file.changed", path=path, hash=result["hash"])
        return result

    @router.get("/models")
    async def agent_models(services: Services):
        return _agent(services).model_views()

    @router.get("/sessions/{session_id}/source")
    async def agent_source(session_id: ID, services: Services):
        return await _agent(services).source(session_id)

    @router.patch("/sessions/{session_id}")
    async def update_agent_session(session_id: ID, payload: AgentModelSetting, services: Services):
        return await _agent(services).set_model(session_id, payload.model)

    @router.get("/config")
    async def get_agent_config(services: Services):
        service = _agent(services)
        sandbox = getattr(service.config, "sandbox", None)
        sandbox_enabled = bool(getattr(sandbox, "enabled", False))
        sandbox_available = shutil.which("bwrap") is not None
        return {"config": service.config.model_dump(mode="json"),
                "models": service.model_views(),
                "readonly_paths": ["Runtime/self.json", "Runtime/Sessions", "Runtime/History", "Runtime/Artifacts", "Runtime/Catalog"],
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

    @router.put("/tools/{plugin_id}")
    async def update_agent_tool(plugin_id: ID, payload: AgentToolSetting,
                                services: Services, lifecycle: Lifecycle):
        """Change the existing PluginRegistry tool setting and reload atomically."""
        report = await lifecycle.update_plugin_setting(plugin_id, payload.enabled)
        return {"plugin_id": plugin_id, "enabled": payload.enabled,
                "generation": services.plugins.generation,
                "report": report.model_dump(mode="json")}

    return router


agent_router = build_agent_router()
