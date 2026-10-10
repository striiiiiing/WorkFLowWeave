"""Non-secret, non-cacheable projections of plugin-owned login sessions."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from workflowweave.channel.login import ChannelLoginManager
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.lifecycle import ApplicationServices
from workflowweave.models import JSONObject

from .dependencies import get_services

router = APIRouter(prefix="/channels/login")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    options: JSONObject = Field(default_factory=dict)


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[0-9]{1,16}$")


def login_manager(request: Request, response: Response) -> ChannelLoginManager:
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.channel_logins


Manager = Annotated[ChannelLoginManager, Depends(login_manager)]
Services = Annotated[ApplicationServices, Depends(get_services)]


@router.post("/{capability}", status_code=201)
async def start(capability: str, payload: LoginRequest, manager: Manager,
                services: Services):
    channel = services.plugins.channelRegister.get(capability)
    if channel is None:
        raise WorkFLowWeaveError("channel_not_found", "渠道能力未注册")
    return await manager.start(channel, payload.options)


@router.get("/sessions/{session_id}")
async def status(session_id: str, manager: Manager):
    return manager.snapshot(session_id)


@router.post("/sessions/{session_id}/verify")
async def verify(session_id: str, payload: VerifyRequest, manager: Manager):
    return await manager.verify(session_id, payload.code)


@router.delete("/sessions/{session_id}", status_code=204)
async def cancel(session_id: str, manager: Manager):
    await manager.cancel(session_id)
