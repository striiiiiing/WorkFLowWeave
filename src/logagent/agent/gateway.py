"""Fixed MCP proxy; immutable session bindings determine its entire scope."""
import json
from dataclasses import asdict

from logagent.errors import LogAgentError
from logagent.models import MCPServerConfig


class MCPGateway:
    def __init__(self, runtime, binding):
        self.runtime = runtime
        self.scope = {key: MCPServerConfig.model_validate(value)
                      for key, value in binding.get("servers", {}).items()}
        self.associations = binding.get("sources", [])
        self.error = binding.get("error")

    def execution(self, arguments):
        return "exclusive" if arguments.get("action") == "call" else "read"

    async def catalog(self, workspace, *, revision):
        path = f"Catalog/{revision}/index.json"
        await workspace.save_runtime(path, json.dumps({
            "servers": self.runtime.status(self.scope), "sources": self.associations,
            "error": self.error,
        }, ensure_ascii=False).encode())
        return path

    async def invoke(self, arguments, context):
        if self.error:
            raise LogAgentError("mcp_binding_unavailable", self.error)
        action = arguments["action"]
        server = arguments.get("server")
        if action == "status":
            return {"status": "success", "servers": self.runtime.status(self.scope)}
        if action in {"list", "search"}:
            return {"status": "success", **self.runtime.listing(
                self.scope, server=server, query=arguments.get("query", ""),
                cursor=arguments.get("cursor", 0), page_size=context.config.plugin_page_size,
            )}
        if not server:
            raise LogAgentError("invalid_argument", "此操作需要 server")
        if action == "load":
            await self.runtime.load(self.scope, server, refresh=arguments.get("refresh", False))
            return {"status": "success", **self.runtime.listing(self.scope, server=server,
                                                               page_size=context.config.plugin_page_size)}
        tool = arguments.get("tool")
        if not tool:
            raise LogAgentError("invalid_argument", "此操作需要原始 tool 名称")
        if action == "describe":
            return {"status": "success", "server": server, "tool": tool,
                    "schema": await self.runtime.describe(self.scope, server, tool)}
        if action != "call":
            raise LogAgentError("invalid_argument", "未知 MCP 操作")
        result = await self.runtime.call(
            self.scope, server, tool, arguments.get("arguments", {}),
            context={"session_id": context.session_id, "turn_id": context.turn_id,
                     "tool_call_id": context.tool_call_id},
        )
        return asdict(result)
