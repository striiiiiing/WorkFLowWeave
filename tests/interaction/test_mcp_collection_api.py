"""Public collection keeps saved call values and a frozen MCP service scope."""

import pytest

from workflowweave.collection.invocation import CollectorInvocation
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import CollectionContext, CollectionResult, MCPServerConfig, SourceConfig


class Runtime:
    async def describe(self, scope, server, tool):
        assert set(scope) == {"server"}
        assert (server, tool) == ("server", "read")
        return {"name": tool, "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}}


class Executor:
    def __init__(self):
        self.mcp = Runtime()
        self.received = None

    async def collect(self, source, context):
        self.received = (source, context)
        return CollectionResult(source_id=source.id, status="success", raw={"content": []})


def invocation():
    executor = Executor()
    sources = {
        "mcp": SourceConfig(id="mcp", call={"kind": "mcp", "server": "server", "tool": "read", "arguments": {"saved": True}}),
        "cli": SourceConfig(id="cli", call={"kind": "cli", "mode": "argv", "executable": "printf", "argv": ["ok"]}),
    }
    scope = {"server": MCPServerConfig(id="server", transport="stdio", command="python3")}
    return CollectorInvocation(sources, scope, executor=executor), executor


async def test_public_mcp_call_preserves_saved_arguments_and_snapshot_scope():
    entry, executor = invocation()
    context = CollectionContext("collection", "session", mcp_servers=entry.mcp_servers)
    schema = await entry.schema("mcp")
    result = await entry.invoke("mcp", {"arguments": {"limit": 3}}, context)
    assert schema["properties"]["arguments"]["properties"]["limit"]["type"] == "integer"
    assert result.source_id == "mcp"
    assert executor.received[0].call.arguments == {"saved": True, "limit": 3}
    assert executor.received[1].mcp_servers is entry.mcp_servers
    assert entry.sources["mcp"].call.arguments == {"saved": True}


async def test_cli_rejects_mcp_arguments_and_exposes_no_call_schema():
    entry, executor = invocation()
    context = CollectionContext("collection", "session", mcp_servers=entry.mcp_servers)
    assert (await entry.schema("cli"))["properties"] == {}
    with pytest.raises(WorkFLowWeaveError, match="CLI 来源不接受 MCP 参数覆盖"):
        await entry.invoke("cli", {"arguments": {"limit": 3}}, context)
    assert executor.received is None
