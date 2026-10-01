"""Workflow-to-Agent MCP binding resolution."""

from __future__ import annotations

from collections.abc import Iterable, Set
from dataclasses import dataclass

from logagent.errors import LogAgentError


@dataclass(frozen=True, slots=True)
class MCPBinding:
    agent_id: str
    mcp_ids: tuple[str, ...]


def resolve_mcp_binding(
    *,
    agent_id: str,
    requested_mcp_ids: Iterable[str],
    enabled_mcp_ids: Set[str],
    allowed_mcp_ids: Set[str],
) -> MCPBinding:
    if type(agent_id) is not str or not agent_id:
        raise LogAgentError("mcp_binding_invalid", "Agent 绑定身份无效")
    requested = tuple(requested_mcp_ids)
    if not requested or any(type(item) is not str or not item for item in requested):
        raise LogAgentError("mcp_binding_invalid", "MCP 绑定不能为空或包含无效 ID")
    if len(requested) != len(set(requested)):
        raise LogAgentError("mcp_binding_invalid", "MCP 绑定包含重复 ID")
    missing = [item for item in requested if item not in enabled_mcp_ids]
    unauthorized = [item for item in requested if item not in allowed_mcp_ids]
    if missing or unauthorized:
        details = {"missing": missing, "unauthorized": unauthorized}
        raise LogAgentError("mcp_binding_invalid", "MCP 绑定未通过准入检查", details)
    return MCPBinding(agent_id=agent_id, mcp_ids=requested)
