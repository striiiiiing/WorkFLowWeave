"""Web transport projection backed by the shared ChannelManager queue."""

from __future__ import annotations

from typing import Any

from logagent.errors import LogAgentError


class WebChannel:
    """Small adapter used by HTTP handlers and embedded integrations."""

    def __init__(self, manager):
        self.manager = manager

    async def dispatch(self, command):
        return await self.manager.dispatch_web(command)

    async def outcome(self, request_id: str, *, session: str | None = None):
        return await self.manager.web_outcome(request_id, session=session)

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return await self.manager.agent_channel.get_session(session_id)

    async def events(self, session_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        return await self.manager.agent_channel.events(session_id, after=after)

    async def wait_events(
        self, session_id: str, *, after: int, wait_seconds: float = 0.5
    ) -> list[dict[str, Any]]:
        return await self.manager.agent_channel.wait_events(
            session_id, after=after, wait_seconds=wait_seconds
        )


class WebChannelType:
    name = "web"
    id_prefix = "web"
    description = "应用内置 Agent Web 对话渠道"
    capabilities = ["conversation"]
    options_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    async def create(self, config, credentials):
        raise LogAgentError("channel_not_notification", "Web 对话渠道由应用装配，不能创建通知实例")
