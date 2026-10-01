from logagent.errors import LogAgentError

from .declaration import ToolDeclaration, field, schema


async def invoke(arguments, context):
    if context.gateway is None:
        raise LogAgentError("mcp_unavailable", "本次会话没有可恢复的 MCP 绑定")
    return await context.gateway.invoke(arguments, context)


plugin = ToolDeclaration(
    "mcp", "Inspect MCP services, list/search tools, describe a tool, or call it. Schemas are returned only on request.",
        schema({
        "action": field("string", "Operation", enum=["list", "search", "describe", "call"]),
        "server": field("string", "Stable server identity"),
        "tool": field("string", "Original MCP tool name"),
        "arguments": field("object", "Complete call arguments; no collection defaults are inherited"),
        "query": field("string", "Filter tools by name or description"),
        "cursor": field("integer", "List offset", minimum=0),
        "refresh": field("boolean", "Refresh this service catalog"),
    }, ["action"]), "read", invoke,
)
