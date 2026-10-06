"""MCP SDK transports; each lease belongs to one execution context."""
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import (
    ClientRequest,
    JSONRPCRequest,
    ServerNotification,
    ServerResult,
    ToolListChangedNotification,
)


class CatalogSession:
    """Observe list-changed notifications while this isolated session is alive."""
    def __init__(self, session, changed):
        self.session, self.changed = session, changed

    async def list_tools(self, cursor=None):
        result = await self.session.list_tools(cursor=cursor)
        if cursor is None:
            self.changed[0] = False
        return result

    async def discover(self):
        return await self.session.send_request(
            ClientRequest(root=JSONRPCRequest(
                method="server/discover", params={}, jsonrpc="2.0", id=1,
            )),
            ServerResult,
        )

    async def call_tool(self, tool, arguments):
        return await self.session.call_tool(tool, arguments)

    @property
    def catalog_changed(self):
        return self.changed[0]


class SDKConnector:
    def __init__(self, credentials):
        self.credentials = credentials

    async def _resolve(self, values):
        return {key: await self.credentials.resolve(value) for key, value in values.items()}

    @asynccontextmanager
    async def connect(self, config, context):
        async with AsyncExitStack() as stack:
            if config.transport == "stdio":
                transport = stdio_client(StdioServerParameters(
                    command=config.command, args=config.args, cwd=config.cwd,
                    env=await self._resolve(config.env),
                ))
            elif config.transport == "sse":
                transport = sse_client(config.url, headers=await self._resolve(config.headers))
            else:
                client = await stack.enter_async_context(httpx.AsyncClient(
                    headers=await self._resolve(config.headers), timeout=config.timeout,
                ))
                transport = streamable_http_client(config.url, http_client=client)
            streams = await stack.enter_async_context(transport)
            changed = [False]
            async def notification(message):
                if isinstance(message, ServerNotification) and isinstance(message.root, ToolListChangedNotification):
                    changed[0] = True
            session = await stack.enter_async_context(ClientSession(
                streams[0], streams[1], message_handler=notification,
            ))
            await session.initialize()
            yield CatalogSession(session, changed)
