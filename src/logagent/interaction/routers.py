"""HTTP projections over lifecycle-owned application services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Path, Query, Response, status

from logagent.collection.invocation import CollectionArguments, CollectorInvocation
from logagent.errors import LogAgentError
from logagent.lifecycle import ApplicationServices
from logagent.models import (
    ID,
    AIConfig,
    CapabilityDescription,
    ChannelConfig,
    CollectionContext,
    CollectionResult,
    DiscoveryReport,
    EncryptedCredential,
    HealthReport,
    JSONObject,
    MCPServerConfig,
    PhaseContent,
    RecoveryAvailability,
    ResourceKind,
    SessionRecord,
    SourceConfig,
    SourceOverride,
    StrictModel,
    WorkflowDefinition,
    WorkflowStage,
)
from logagent.scheduling import cron_trigger, describe_cron

from .dependencies import Lifecycle as LifecycleProtocol
from .dependencies import get_lifecycle, get_services
from .schemas import (
    CancelResponse,
    CronPreviewRequest,
    CronPreviewResponse,
    PhaseQuery,
    ProtectCredentialRequest,
    RecoveryQuery,
    ReloadQuery,
    ReloadResponse,
    ResumeRequest,
    SessionListQuery,
    SessionQuery,
    TriggerRequest,
    TriggerResponse,
)
from .sse import HEARTBEAT, SSEMessage, sse_response

router = APIRouter()
Services = Annotated[ApplicationServices, Depends(get_services)]
Lifecycle = Annotated[LifecycleProtocol, Depends(get_lifecycle)]


@router.post("/workflows/cron/preview", response_model=CronPreviewResponse)
async def preview_cron(payload: CronPreviewRequest) -> CronPreviewResponse:
    trigger = cron_trigger(payload.expression, payload.timezone)
    return CronPreviewResponse(
        description=describe_cron(payload.expression, trigger),
        timezone=str(trigger.timezone),
        next_run_at=trigger.get_next_fire_time(None, datetime.now(UTC)),
    )


async def _save_resource(
    services: ApplicationServices,
    kind: ResourceKind,
    payload: StrictModel,
    *,
    mode: Literal["create", "replace"],
) -> StrictModel:
    if kind == "workflows":
        return await services.workflow.save(payload, mode=mode)
    return await asyncio.to_thread(services.resources.save, kind, payload, mode=mode)


async def _get_resource(
    services: ApplicationServices,
    kind: ResourceKind,
    ident: str,
) -> StrictModel:
    value = await asyncio.to_thread(services.resources.get, kind, ident)
    if value is None:
        raise LogAgentError("not_found", "资源不存在", {"kind": kind, "id": ident})
    return value


@router.post("/sources", response_model=SourceConfig, status_code=status.HTTP_201_CREATED)
async def create_source(payload: SourceConfig, services: Services):
    return await _save_resource(services, "sources", payload, mode="create")


@router.put("/sources/{ident}", response_model=SourceConfig)
async def replace_source(ident: ID, payload: SourceConfig, services: Services):
    if ident != payload.id:
        raise LogAgentError("invalid_argument", "路径 ID 与资源 ID 不一致")
    return await _save_resource(services, "sources", payload, mode="replace")


@router.post("/sources/{ident}/resolve", response_model=SourceConfig)
async def resolve_source(ident: ID, payload: SourceOverride, services: Services):
    return await asyncio.to_thread(services.resources.resolve_source, ident, payload)


def _collector_invocation(services: ApplicationServices) -> CollectorInvocation:
    # No await or Agent workspace lock between snapshot capture and execution:
    # Shell can call this API while already holding the workspace write lock.
    snapshot = services.resources.invocation_snapshot()
    return CollectorInvocation(
        snapshot["sources"], snapshot["mcp_servers"], executor=services.collectors,
    )


@router.get("/sources/{ident}/call-schema", response_model=JSONObject)
async def source_call_schema(ident: ID, services: Services):
    return await _collector_invocation(services).schema(ident)


@router.post("/sources/{ident}/collect", response_model=CollectionResult)
async def collect_source(ident: ID, payload: CollectionArguments, services: Services):
    invocation = _collector_invocation(services)
    context = CollectionContext(
        "collection", uuid4().hex, services.log_path, services.credentials, services.session_view,
        dict(invocation.mcp_servers),
    )
    return await invocation.invoke(ident, payload, context)


@router.post("/mcp_servers", response_model=MCPServerConfig, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(payload: MCPServerConfig, services: Services):
    return await _save_resource(services, "mcp_servers", payload, mode="create")


@router.put("/mcp_servers/{ident}", response_model=MCPServerConfig)
async def replace_mcp_server(ident: ID, payload: MCPServerConfig, services: Services):
    if ident != payload.id:
        raise LogAgentError("invalid_argument", "路径 ID 与资源 ID 不一致")
    return await _save_resource(services, "mcp_servers", payload, mode="replace")


def _mcp_scope(services: ApplicationServices) -> dict[str, MCPServerConfig]:
    return {item.id: item for item in services.resources.list("mcp_servers")}


@router.get("/mcp/catalog/status")
async def mcp_catalog_status(services: Services):
    return services.collectors.mcp.status(_mcp_scope(services))


@router.get("/mcp/catalog")
async def mcp_catalog(
    services: Services, server: ID | None = None, query: str = "",
    cursor: int = Query(default=0, ge=0), page_size: int = Query(default=20, ge=1, le=100),
):
    return services.collectors.mcp.listing(
        _mcp_scope(services), server=server, query=query, cursor=cursor, page_size=page_size,
    )


@router.post("/mcp/catalog/{server}/load")
async def load_mcp_catalog(server: ID, services: Services, refresh: bool = False):
    tools = await services.collectors.mcp.load(_mcp_scope(services), server, refresh=refresh)
    return {"server": server, "tool_count": len(tools)}


@router.get("/mcp/catalog/{server}/tools/{tool:path}")
async def describe_mcp_tool(server: ID, tool: str, services: Services):
    return await services.collectors.mcp.describe(_mcp_scope(services), server, tool)


@router.post("/ai", response_model=AIConfig, status_code=status.HTTP_201_CREATED)
async def create_ai(payload: AIConfig, services: Services):
    return await _save_resource(services, "ai", payload, mode="create")


@router.post("/ai/discover-models", response_model=list[str])
async def discover_ai_models(payload: AIConfig, services: Services, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await services.ai.list_models(payload)


@router.post("/ai/{ident}/check-connection", response_model=list[str])
async def check_ai_connection(ident: ID, services: Services, response: Response):
    """Explicit model discovery; saving a provider never calls the upstream server."""
    response.headers["Cache-Control"] = "no-store"
    config = await _get_resource(services, "ai", ident)
    return await services.ai.list_models(config)


@router.put("/ai/{ident}", response_model=AIConfig)
async def replace_ai(ident: ID, payload: AIConfig, services: Services):
    if ident != payload.id:
        raise LogAgentError("invalid_argument", "路径 ID 与资源 ID 不一致")
    return await _save_resource(services, "ai", payload, mode="replace")


@router.post("/channels", response_model=ChannelConfig, status_code=status.HTTP_201_CREATED)
async def create_channel(payload: ChannelConfig, services: Services):
    return await _save_resource(services, "channels", payload, mode="create")


@router.put("/channels/{ident}", response_model=ChannelConfig)
async def replace_channel(ident: ID, payload: ChannelConfig, services: Services):
    if ident != payload.id:
        raise LogAgentError("invalid_argument", "路径 ID 与资源 ID 不一致")
    return await _save_resource(services, "channels", payload, mode="replace")


@router.post("/workflows", response_model=WorkflowDefinition, status_code=status.HTTP_201_CREATED)
async def create_workflow(payload: WorkflowDefinition, services: Services):
    return await _save_resource(services, "workflows", payload, mode="create")


@router.put("/workflows/{ident}", response_model=WorkflowDefinition)
async def replace_workflow(ident: ID, payload: WorkflowDefinition, services: Services):
    if ident != payload.id:
        raise LogAgentError("invalid_argument", "路径 ID 与资源 ID 不一致")
    return await _save_resource(services, "workflows", payload, mode="replace")


@router.post(
    "/workflows/trigger",
    response_model=TriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_workflow(
    payload: TriggerRequest,
    response: Response,
    services: Services,
):
    workflow = payload.snapshot if payload.snapshot is not None else payload.workflow_id
    session_id = await services.workflow.trigger(workflow)
    response.headers["Location"] = f"/api/sessions/{session_id}"
    return TriggerResponse(session_id=session_id)


@router.post(
    "/workflows/{workflow_id}/run",
    response_model=TriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_workflow(workflow_id: ID, response: Response, services: Services):
    session_id = await services.workflow.trigger(workflow_id)
    response.headers["Location"] = f"/api/sessions/{session_id}"
    return TriggerResponse(session_id=session_id)


@router.get("/sessions", response_model=list[SessionRecord])
async def list_sessions(
    services: Services,
    query: Annotated[SessionListQuery, Query()],
):
    return await services.session_view.list_sessions(
        query.workflow_id,
        workflow_name=query.workflow_name,
        session_id=query.session_id,
        status=query.status,
        limit=query.limit,
        offset=query.offset,
        after=query.after,
        before=query.before,
    )


@router.get("/sessions/{session_id}", response_model=SessionRecord)
async def get_session(
    session_id: ID,
    services: Services,
    query: Annotated[SessionQuery, Query()],
):
    return await services.session_view.get_session(session_id, version=query.version)


@router.get("/sessions/{session_id}/recovery", response_model=RecoveryAvailability)
async def get_recovery_availability(
    session_id: ID, services: Services, query: Annotated[RecoveryQuery, Query()],
):
    return await services.workflow.recovery_availability(
        session_id, **query.model_dump(exclude_none=True),
    )


@router.get("/sessions/{session_id}/phases/{stage}", response_model=PhaseContent)
@router.get("/sessions/{session_id}/stages/{stage}", response_model=PhaseContent)
@router.get("/sessions/{session_id}/artifacts/{stage}", response_model=PhaseContent)
async def get_phase_content(
    session_id: ID,
    stage: WorkflowStage,
    services: Services,
    query: Annotated[PhaseQuery, Query()],
):
    return await services.session_view.get_phase_content(
        session_id,
        stage,
        version=query.version,
    )


@router.post(
    "/sessions/{session_id}/recover",
    response_model=TriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@router.post(
    "/sessions/{session_id}/resume",
    response_model=TriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def recover_session(
    session_id: ID, response: Response, services: Services, payload: ResumeRequest | None = None,
):
    recovered = await services.workflow.resume(
        session_id, **(payload.model_dump(exclude_none=True) if payload else {}),
    )
    response.headers["Location"] = f"/api/sessions/{recovered}"
    return TriggerResponse(session_id=recovered)


@router.post("/sessions/{session_id}/cancel", response_model=CancelResponse)
async def cancel_session(session_id: ID, services: Services):
    cancelled = await services.workflow.cancel(session_id)
    return CancelResponse(session_id=session_id, cancelled=cancelled)


@router.get("/plugins", response_model=list[CapabilityDescription])
async def list_plugins(services: Services):
    return [
        *services.plugins.collectorRegister.describe(),
        *services.plugins.channelRegister.describe(),
        *services.plugins.toolRegister.describe(),
    ]


@router.get("/health", response_model=HealthReport)
async def health(lifecycle: Lifecycle):
    report = await lifecycle.health()
    return Response(
        content=report.model_dump_json(),
        media_type="application/json",
        status_code=(
            status.HTTP_503_SERVICE_UNAVAILABLE
            if report.status == "unavailable"
            else status.HTTP_200_OK
        ),
    )


@router.post("/reload", response_model=ReloadResponse)
async def reload(
    lifecycle: Lifecycle,
    query: Annotated[ReloadQuery, Query()],
):
    result = await lifecycle.reload(query.scope)
    report = result if isinstance(result, DiscoveryReport) else None
    return ReloadResponse(scope=query.scope, report=report)


@router.post("/credentials/protect", response_model=EncryptedCredential)
async def protect_credential(payload: ProtectCredentialRequest, response: Response, services: Services):
    response.headers["Cache-Control"] = "no-store"
    return await asyncio.to_thread(services.credentials.protect, payload.plaintext.get_secret_value())


@router.get("/{kind}", response_model=list[JSONObject])
async def list_resources(
    kind: Annotated[ResourceKind, Path()],
    services: Services,
):
    values = await asyncio.to_thread(services.resources.list, kind)
    return [value.model_dump(mode="json") for value in values]


@router.get("/{kind}/{ident}", response_model=JSONObject)
async def get_resource(
    kind: Annotated[ResourceKind, Path()],
    ident: ID,
    services: Services,
):
    value = await _get_resource(services, kind, ident)
    return value.model_dump(mode="json")


@router.delete("/{kind}/{ident}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(
    kind: Annotated[ResourceKind, Path()],
    ident: ID,
    services: Services,
):
    await asyncio.to_thread(services.resources.delete, kind, ident)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


_WORKFLOW_SSE_HEARTBEAT_SECONDS = 15
_WORKFLOW_TERMINAL = {"completed", "partial", "failed", "cancelled", "interrupted"}


@router.get("/sessions/{session_id}/events")
async def workflow_events(session_id: ID, services: Services):
    """只注册观察者；ready 后客户端查询同一投影以补齐连接窗口。"""
    subscription = services.workflow.progress_hub.subscribe(session_id)
    queue = await subscription.__aenter__()
    try:
        initial = await services.session_view.get_session(session_id)
    except BaseException:
        await subscription.__aexit__(None, None, None)
        raise

    async def stream():
        try:
            current = initial
            yield SSEMessage(data=current.model_dump(mode="json"), event="snapshot")
            while current.status not in _WORKFLOW_TERMINAL:
                try:
                    item = await asyncio.wait_for(queue.get(), _WORKFLOW_SSE_HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield HEARTBEAT
                    continue
                if item is None:
                    return
                if item.version <= current.version:
                    continue
                current = item
                yield SSEMessage(data=current.model_dump(mode="json"), event="snapshot")
        finally:
            await subscription.__aexit__(None, None, None)

    return sse_response(stream())
