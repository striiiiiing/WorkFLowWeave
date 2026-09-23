"""HTTP projections over lifecycle-owned application services."""

from __future__ import annotations

import asyncio
from pathlib import Path as FilePath
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
    PhaseContent,
    RecoveryAvailability,
    ResourceKind,
    SessionRecord,
    SetterTemplate,
    SourceConfig,
    StrictModel,
    WorkflowDefinition,
    WorkflowStage,
)

from .dependencies import Lifecycle as LifecycleProtocol
from .dependencies import get_lifecycle, get_services
from .schemas import (
    CancelResponse,
    PhaseQuery,
    ProtectCredentialRequest,
    ReloadQuery,
    ReloadResponse,
    SessionListQuery,
    SessionQuery,
    TriggerRequest,
    TriggerResponse,
)

router = APIRouter()
Services = Annotated[ApplicationServices, Depends(get_services)]
Lifecycle = Annotated[LifecycleProtocol, Depends(get_lifecycle)]


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


def _collector_invocation(services: ApplicationServices) -> CollectorInvocation:
    # No await or Agent workspace lock between snapshot capture and execution:
    # Shell can call this API while already holding the workspace write lock.
    snapshot = services.resources.invocation_snapshot()
    return CollectorInvocation(
        snapshot["sources"], services.plugins.collectorRegister.describe(),
        executor=services.collectors, data_dir=FilePath(services.system_config.data_dir),
    )


@router.get("/sources/{ident}/call-schema", response_model=JSONObject)
async def source_call_schema(ident: ID, services: Services):
    return _collector_invocation(services).schema(ident)


@router.post("/sources/{ident}/collect", response_model=CollectionResult)
async def collect_source(ident: ID, payload: CollectionArguments, services: Services):
    invocation = _collector_invocation(services)
    context = CollectionContext(
        "collection", uuid4().hex, services.log_path, services.credentials, services.session_view,
    )
    return await invocation.invoke(ident, payload, context)


@router.post("/setters", response_model=SetterTemplate, status_code=status.HTTP_201_CREATED)
async def create_setter(payload: SetterTemplate, services: Services):
    return await _save_resource(services, "setters", payload, mode="create")


@router.put("/setters/{ident}", response_model=SetterTemplate)
async def replace_setter(ident: ID, payload: SetterTemplate, services: Services):
    if ident != payload.id:
        raise LogAgentError("invalid_argument", "路径 ID 与资源 ID 不一致")
    return await _save_resource(services, "setters", payload, mode="replace")


@router.post("/ai", response_model=AIConfig, status_code=status.HTTP_201_CREATED)
async def create_ai(payload: AIConfig, services: Services):
    return await _save_resource(services, "ai", payload, mode="create")


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
async def get_recovery_availability(session_id: ID, services: Services):
    return await services.workflow.recovery_availability(session_id)


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
async def recover_session(session_id: ID, response: Response, services: Services):
    recovered = await services.workflow.recover(session_id)
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
