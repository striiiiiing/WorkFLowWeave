"""Local injection and inspection for the explicitly configured test transport."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from logagent.channel.conversation import InboundMessage
from logagent.errors import LogAgentError
from logagent.lifecycle import ApplicationServices
from logagent.models import ID

from .dependencies import get_services

Services = Annotated[ApplicationServices, Depends(get_services)]
router = APIRouter(prefix="/channels")


def _test_channel(services, channel_id):
    config = services.resources.get("channels", channel_id)
    if config is None or config.channel != "test":
        raise LogAgentError("channel_not_found", "本地测试渠道不存在")
    if not config.enabled or not config.agent_enabled:
        raise LogAgentError("channel_disabled", "测试渠道未启用 Agent 接收")
    return config, services.channels.receiver(config)


@router.post("/{channel_id}/test/messages", status_code=202)
async def inject(channel_id: ID, message: InboundMessage, services: Services):
    _, channel = _test_channel(services, channel_id)
    return await channel.inject(message)


@router.get("/{channel_id}/test/messages")
async def outbox(channel_id: ID, services: Services, after: int = Query(0, ge=0)):
    _, channel = _test_channel(services, channel_id)
    return channel.outbox(after=after)


@router.post("/{channel_id}/test/outcome")
async def outcome(channel_id: ID, message: InboundMessage, services: Services):
    config, _ = _test_channel(services, channel_id)
    return await services.channels.outcome(config, message)


@router.get("/status")
async def status(services: Services):
    runtime = services.channels
    receivers = {}
    for ident, config in runtime.configs.items():
        instance = services.channels.receiver(config)
        probe = getattr(instance, "receiver_status", None)
        receivers[ident] = probe() if probe is not None else {"state": "attached"}
    return {"receiving": sorted(runtime.configs), "receivers": receivers, "errors": runtime.errors}
