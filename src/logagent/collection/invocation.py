"""Public single-source collection using a captured resource snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from pydantic import Field, ValidationError

from logagent.config.calls import resolve_source_call
from logagent.errors import LogAgentError, validation_error
from logagent.models import (
    CollectionContext,
    CollectionResult,
    JSONObject,
    MCPServerConfig,
    SourceConfig,
    SourceOverride,
    StrictModel,
)


class CollectionArguments(StrictModel):
    arguments: JSONObject = Field(default_factory=dict)


class CollectionExecutor(Protocol):
    async def collect(self, source: SourceConfig, context: CollectionContext) -> CollectionResult: ...


class CollectorInvocation:
    """Use an already expanded resource snapshot and an injected single-call executor.

    Adapters capture these references synchronously before invoking; this service
    owns neither a plugin registry nor the Agent workspace scheduler.
    """

    def __init__(
        self,
        sources: Mapping[str, SourceConfig],
        mcp_servers: Mapping[str, MCPServerConfig],
        *,
        executor: CollectionExecutor,
    ):
        self.sources = sources
        self.mcp_servers = mcp_servers
        self._executor = executor

    def target(self, ident: str) -> SourceConfig:
        source = self.sources.get(ident)
        if source is None or not source.enabled:
            raise LogAgentError("target_unavailable", "目标未配置或未启用")
        return source

    async def schema(self, ident: str) -> JSONObject:
        source = self.target(ident)
        if source.call is None or source.call.kind != "mcp":
            return {"type": "object", "properties": {}, "additionalProperties": False}
        tool = await self._executor.mcp.describe(
            self.mcp_servers, source.call.server, source.call.tool,
        )
        return {
            "type": "object",
            "properties": {"arguments": tool["inputSchema"]},
            "additionalProperties": False,
        }

    async def invoke(
        self, ident: str, arguments: object, context: CollectionContext,
    ) -> CollectionResult:
        source = self.target(ident)
        try:
            values = CollectionArguments.model_validate(arguments)
        except ValidationError as exc:
            raise validation_error(exc, code="invalid_argument") from None
        if source.call is None:
            raise LogAgentError("invalid_argument", "历史 Collector 来源不支持交互式 call")
        if source.call.kind == "cli" and values.arguments:
            raise LogAgentError("invalid_argument", "CLI 来源不接受 MCP 参数覆盖")
        override = SourceOverride(arguments=values.arguments) if values.arguments else None
        resolved = resolve_source_call(source, {}, override)
        return await self._executor.collect(resolved, context)
