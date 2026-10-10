"""MCP 目录、派发与 stdio 契约；真实子进程验证协议及启动失败的诊断。"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import McpError
from mcp.types import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    CallToolResult,
    ErrorData,
    ListToolsResult,
    TextContent,
    Tool,
)

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.mcp import MCPRuntime, SDKConnector
from workflowweave.mcp.transport import CatalogSession
from workflowweave.models import MCPServerConfig


def config(id="one", **kwargs):
    return MCPServerConfig(id=id, transport="stdio", command=sys.executable, **kwargs)


class Connector:
    def __init__(self):
        self.opens = 0
        self.calls = []
        self.tools = [Tool(name="echo", inputSchema={"type": "object", "properties": {
            "value": {"type": "string"}}, "required": ["value"], "additionalProperties": False})]
        self.error = None

    @asynccontextmanager
    async def connect(self, config, context):
        self.opens += 1
        yield self

    async def list_tools(self, cursor=None):
        return ListToolsResult(tools=self.tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.error:
            raise self.error
        return CallToolResult(content=[TextContent(type="text", text="false")])


async def test_lazy_catalog_scope_schema_and_refresh(tmp_path):
    connector = Connector()
    runtime = MCPRuntime(connector, cache_dir=tmp_path)
    scope = {"one": config(), "two": config("two")}
    assert runtime.listing(scope)["load_servers"] == ["one", "two"]
    assert connector.opens == 0
    await runtime.load(scope, "one")
    await runtime.describe(scope, "one", "echo")
    assert connector.opens == 1 and not connector.calls
    assert runtime.listing(scope)["entries"][0]["server"] == "one"
    with pytest.raises(WorkFLowWeaveError, match="范围"):
        await runtime.call(scope, "other", "echo", {}, context={})
    with pytest.raises(WorkFLowWeaveError):
        await runtime.call(scope, "one", "echo", {"value": 1}, context={})
    assert not connector.calls
    connector.tools = []
    with pytest.raises(WorkFLowWeaveError, match="不存在"):
        await runtime.call(scope, "one", "echo", {"value": "a"}, context={})
    assert runtime.listing(scope, server="one")["entries"] == []
    cached = MCPRuntime(connector, cache_dir=tmp_path)
    assert cached.status(scope)[0]["state"] == "cached"
    changed = {"one": config(args=["changed"])}
    assert cached.status(changed)[0]["state"] == "unloaded"


async def test_dispatched_failure_is_unknown_and_not_replayed():
    connector = Connector()
    connector.error = ConnectionError("dropped")
    runtime = MCPRuntime(connector)
    result = await runtime.call({"one": config()}, "one", "echo", {"value": "a"}, context={"session_id": "s"})
    assert result.phase == "dispatched" and not result.result_known
    assert len(connector.calls) == 1
    assert result.context == {"session_id": "s"}


async def test_probe_refreshes_catalog_and_records_health():
    connector = Connector()
    runtime = MCPRuntime(connector)
    report = await runtime.probe({"one": config()}, "one")
    assert report.status == "healthy"
    assert report.tool_count == 1
    assert report.checked_at is not None
    status = runtime.status({"one": config()})[0]
    assert status["health"]["status"] == "healthy"


async def test_probe_returns_unhealthy_report_without_hiding_failure():
    class BrokenConnector(Connector):
        async def list_tools(self, cursor=None):
            raise ConnectionError("offline")

    runtime = MCPRuntime(BrokenConnector())
    report = await runtime.probe({"one": config()}, "one")
    assert report.status == "unhealthy"
    assert report.error is not None
    assert report.error.code == "mcp_directory_failed"


async def test_probe_reports_disabled_server_without_connecting():
    connector = Connector()
    runtime = MCPRuntime(connector)
    report = await runtime.probe({"one": config(enabled=False)}, "one")
    assert report.status == "disabled"
    assert connector.opens == 0


async def test_discover_method_not_found_falls_back_once_for_paginated_catalog():
    class LegacyConnector(Connector):
        def __init__(self):
            super().__init__()
            self.discover_calls = 0
            self.cursors = []

        async def discover(self):
            self.discover_calls += 1
            raise McpError(ErrorData(code=METHOD_NOT_FOUND, message="Method not found"))

        async def list_tools(self, cursor=None):
            self.cursors.append(cursor)
            tools = [Tool(name="first", inputSchema={"type": "object"})]
            if cursor is None:
                return ListToolsResult(tools=tools, nextCursor="next")
            return ListToolsResult(tools=[Tool(name="second", inputSchema={"type": "object"})])

    connector = LegacyConnector()
    tools = await MCPRuntime(connector).load({"one": config()}, "one")
    assert [tool["name"] for tool in tools] == ["first", "second"]
    assert connector.discover_calls == 1
    assert connector.cursors == [None, "next"]


@pytest.mark.parametrize(
    "error",
    [
        McpError(ErrorData(code=-32000, message="unknown authentication failure")),
        McpError(ErrorData(code=INVALID_PARAMS, message="Invalid request parameters")),
        AttributeError("bug inside discover"),
        NotImplementedError("unsupported internal operation"),
    ],
)
async def test_discover_failures_other_than_method_not_found_do_not_fall_back(error):
    class BrokenConnector(Connector):
        def __init__(self):
            super().__init__()
            self.list_calls = 0

        async def discover(self):
            raise error

        async def list_tools(self, cursor=None):
            self.list_calls += 1
            return await super().list_tools(cursor)

    connector = BrokenConnector()
    report = await MCPRuntime(connector).probe({"one": config()}, "one")
    assert report.status == "unhealthy"
    assert connector.list_calls == 0


@pytest.mark.parametrize("response", [{}, {"tools": "invalid"}, {"tools": [{}]},
                                      {"tools": [{"name": "broken"}]}])
async def test_malformed_discover_response_is_unhealthy_without_fallback(response):
    class BrokenConnector(Connector):
        async def discover(self):
            return response

        async def list_tools(self, cursor=None):
            pytest.fail("invalid discover responses must not fall back")

    report = await MCPRuntime(BrokenConnector()).probe({"one": config()}, "one")
    assert report.status == "unhealthy"


async def test_valid_discover_catalog_does_not_list_tools():
    class DiscoverConnector(Connector):
        async def discover(self):
            return {"tools": [tool.model_dump(by_alias=True) for tool in self.tools]}

        async def list_tools(self, cursor=None):
            pytest.fail("discover already supplied the catalog")

    tools = await MCPRuntime(DiscoverConnector()).load({"one": config()}, "one")
    assert [tool["name"] for tool in tools] == ["echo"]


@pytest.mark.parametrize("message,data,expected_code", [
    ("Invalid request parameters", "", METHOD_NOT_FOUND),
    ("Invalid request parameters", {"field": "params"}, INVALID_PARAMS),
    ("Invalid request parameters", None, INVALID_PARAMS),
    ("unsupported authentication method", "", INVALID_PARAMS),
])
async def test_sdk_adapter_only_normalizes_the_unknown_request_signature(message, data, expected_code):
    class Session:
        async def send_request(self, request, result_type):
            assert request.method == "server/discover" and request.params == {}
            raise McpError(ErrorData(code=INVALID_PARAMS, message=message, data=data))

    with pytest.raises(McpError) as caught:
        await CatalogSession(Session(), [False]).discover()
    assert caught.value.error.code == expected_code


async def test_real_stdio_mcp_roundtrip(tmp_path):
    runtime = MCPRuntime(SDKConnector(None), cache_dir=tmp_path)
    scope = {"one": config(args=[str(Path(__file__).with_name("stdio_server.py"))])}
    async with asyncio.timeout(15):
        tools = await runtime.load(scope, "one")
        assert {tool["name"] for tool in tools} == {"echo", "fail"}
        result = await runtime.call(scope, "one", "echo", {"value": "actual", "count": 0}, context={"session_id": "real"})
        assert result.status == "success" and result.result_known
        assert result.raw["structuredContent"] == {"value": "actual", "count": 0}
        failed = await runtime.call(scope, "one", "fail", {}, context={})
        assert failed.status == "tool_error" and failed.raw["isError"]


async def test_missing_stdio_command_has_actionable_diagnostic(tmp_path):
    runtime = MCPRuntime(SDKConnector(None))
    missing = str(tmp_path / "missing-mcp-command")
    scope = {"one": MCPServerConfig(id="one", transport="stdio", command=missing)}
    with pytest.raises(WorkFLowWeaveError) as caught:
        await runtime.load(scope, "one")
    error = caught.value.info
    assert error.code == "mcp_directory_failed"
    assert error.details["exception_type"] == "FileNotFoundError"
    assert missing in error.details["reason"]
    assert "后端" in error.details["reason"]
    assert runtime.status(scope)[0]["state"] == "failed"
    assert runtime.listing(scope)["load_servers"] == ["one"]
