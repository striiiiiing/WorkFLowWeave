"""HTTP/SSE projection for the independent Agent runtime."""

from __future__ import annotations

import shutil
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from pydantic import Field

from logagent.agent.config import AgentConfig as AgentRuntimeConfig
from logagent.agent.workspace import RuntimeIdentity
from logagent.channel.agent import AgentCommand
from logagent.errors import LogAgentError
from logagent.lifecycle import ApplicationServices
from logagent.models import ID, StrictModel

from .channel_routers import dispatch_web, stream_agent_events
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
    model: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=120)


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
        command = AgentCommand(
            action="workflow" if payload.workflow_session_id or payload.workflow_id else "new",
            model=payload.model,
            workflow_session_id=payload.workflow_session_id,
            workflow_id=payload.workflow_id,
            workflow_result=payload.workflow_result,
        )
        return (await dispatch_web(services, command))["result"]

    @router.post("/commands", status_code=status.HTTP_202_ACCEPTED)
    async def agent_command(payload: AgentCommand, services: Services):
        return await dispatch_web(services, payload)

    @router.get("/sessions/{session_id}")
    async def get_agent_session(session_id: ID, services: Services):
        return await _agent(services).get_session(session_id)

    @router.post("/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
    async def send_agent_message(session_id: ID, payload: AgentMessage, services: Services, response: Response):
        accepted = (await dispatch_web(services, AgentCommand(
            channel="web", session=session_id, request_id=payload.request_id,
            text=payload.text, action="message",
        )))["result"]
        response.headers["Location"] = f"/api/agents/sessions/{session_id}/events"
        return accepted

    @router.post("/sessions/{session_id}/append", status_code=status.HTTP_202_ACCEPTED)
    async def append_agent_message(session_id: ID, payload: AgentMessage,
                                   services: Services, response: Response):
        accepted = (await dispatch_web(services, AgentCommand(
            channel="web", session=session_id, request_id=payload.request_id,
            text=payload.text, action="append",
        )))["result"]
        response.headers["Location"] = f"/api/agents/sessions/{session_id}/events"
        return accepted

    @router.post("/sessions/{session_id}/fork", status_code=status.HTTP_201_CREATED)
    async def fork_agent_session(session_id: ID, payload: AgentForkRequest,
                                 services: Services):
        return (await dispatch_web(services, AgentCommand(
            channel="web", session=session_id, action="fork", turn_id=payload.turn_id,
            model=payload.model, message_id=payload.message_id,
        )))["result"]

    @router.get("/sessions/{session_id}/history")
    async def agent_history(session_id: ID, services: Services):
        return await _agent(services).history(session_id)

    @router.post("/sessions/{session_id}/cancel")
    async def cancel_agent_session(session_id: ID, services: Services):
        return (await dispatch_web(services, AgentCommand(
            channel="web", session=session_id, action="stop",
        )))["result"]

    @router.post("/sessions/{session_id}/compact", status_code=status.HTTP_202_ACCEPTED)
    async def compact_agent_session(session_id: ID, services: Services):
        return (await dispatch_web(services, AgentCommand(
            channel="web", session=session_id, action="compact",
        )))["result"]

    @router.get("/sessions/{session_id}/events")
    async def agent_events(session_id: ID, request: Request,
                           services: Services, after: int = Query(0, ge=0),
                           last_event_id: str | None = Header(None)):
        return await stream_agent_events(
            services.channels.web_channel, session_id, request,
            after=after, last_event_id=last_event_id,
        )

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
        if (payload.model is None) == (payload.title is None):
            raise LogAgentError("invalid_argument", "只能修改模型或话题名称之一")
        if payload.model is not None:
            return await _agent(services).set_model(session_id, payload.model)
        return await _agent(services).set_title(session_id, payload.title)

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
