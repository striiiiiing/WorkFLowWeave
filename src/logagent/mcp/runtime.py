"""One metadata/catalog and dispatch implementation for every MCP consumer."""
from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from logagent.errors import LogAgentError
from logagent.models import MCPServerConfig, copy_model
from logagent.schema import validate_instance


class Connector(Protocol):
    def connect(self, config: MCPServerConfig, context: Mapping[str, Any]): ...


def version(config: MCPServerConfig) -> str:
    payload = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class MCPExecution:
    server: str
    tool: str
    context: dict
    status: str
    phase: str
    result_known: bool
    raw: dict | None = None
    error: str | None = None
    count_state: str = "count_unavailable"


class MCPRuntime:
    def __init__(self, connector: Connector, *, cache_dir: Path | None = None):
        self.connector = connector
        self.cache_dir = cache_dir
        self._catalogs: dict[str, list[dict]] = {}
        self._active: dict[str, int] = {}
        self._errors: dict[str, str] = {}

    @staticmethod
    def _bound(scope, server):
        config = scope.get(server)
        if config is None or config.id != server:
            raise LogAgentError("mcp_out_of_scope", "MCP 服务不在本次绑定范围", {"server": server})
        if not config.enabled:
            raise LogAgentError("mcp_disabled", "绑定的 MCP 服务已停用", {"server": server})
        return copy_model(config)

    def _cached(self, config):
        key = version(config)
        if key not in self._catalogs and self.cache_dir is not None:
            path = self.cache_dir / f"{key}.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    if data["version"] != key or not isinstance(data["tools"], list):
                        raise ValueError("metadata version mismatch")
                    self._catalogs[key] = data["tools"]
                except (OSError, ValueError, KeyError) as exc:
                    raise LogAgentError("mcp_cache_invalid", "MCP 元数据缓存损坏") from exc
        return self._catalogs.get(key)

    def status(self, scope):
        entries = []
        for server, config in scope.items():
            key = version(config)
            cached = self._cached(config)
            state = ("connected" if self._active.get(key) else "failed" if key in self._errors
                     else "cached" if cached is not None else "unloaded")
            entries.append({"server": server, "version": key, "state": state,
                            "enabled": config.enabled, "error": self._errors.get(key)})
        return entries

    async def _refresh(self, session, config):
        tools, cursor, seen = [], None, set()
        while True:
            try:
                page = await session.discover()
                discovered = page.get("tools") if isinstance(page, dict) else getattr(page, "tools", None)
                if discovered is not None:
                    tools.extend(
                        item.model_dump(mode="json", by_alias=True, exclude_none=True)
                        if hasattr(item, "model_dump") else dict(item)
                        for item in discovered
                    )
                    break
            except Exception as exc:
                if not isinstance(exc, (AttributeError, NotImplementedError)) and not any(
                    marker in str(exc).lower() for marker in ("method", "unsupported", "unknown")
                ):
                    raise
            page = await session.list_tools(cursor=cursor)
            tools.extend(tool.model_dump(mode="json", by_alias=True, exclude_none=True)
                         for tool in page.tools)
            cursor = page.nextCursor
            if cursor is None:
                break
            if cursor in seen:
                raise LogAgentError("mcp_catalog_invalid", "目录分页游标重复")
            seen.add(cursor)
        names = [tool["name"] for tool in tools]
        if len(names) != len(set(names)):
            raise LogAgentError("mcp_catalog_invalid", "同一服务的工具名称重复")
        key = version(config)
        self._catalogs[key] = deepcopy(tools)
        self._errors.pop(key, None)
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            # Cache only metadata, never configuration, credentials or call results.
            import os
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", dir=self.cache_dir, delete=False) as out:
                temporary = Path(out.name)
                json.dump({"version": key, "tools": tools}, out, ensure_ascii=False)
            try:
                os.replace(temporary, self.cache_dir / f"{key}.json")
            finally:
                await asyncio.to_thread(temporary.unlink, missing_ok=True)
        return tools

    async def load(self, scope, server, *, refresh=False, context=None):
        config = self._bound(scope, server)
        cached = self._cached(config)
        if cached is not None and not refresh:
            return deepcopy(cached)
        key = version(config)
        try:
            async with asyncio.timeout(config.timeout):
                async with self.connector.connect(config, context or {}) as session:
                    self._active[key] = self._active.get(key, 0) + 1
                    try:
                        return deepcopy(await self._refresh(session, config))
                    finally:
                        self._active[key] -= 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._errors[key] = type(exc).__name__
            raise LogAgentError("mcp_directory_failed", "MCP 工具目录加载失败",
                                {"server": server, "exception_type": type(exc).__name__}) from exc

    def listing(self, scope, *, server=None, query="", cursor=0, page_size=20):
        if type(cursor) is not int or cursor < 0 or not 1 <= page_size <= 100:
            raise LogAgentError("invalid_argument", "目录分页参数无效")
        selected = scope if server is None else {server: self._bound(scope, server)}
        entries, pending = [], []
        for ident, config in selected.items():
            tools = self._cached(config)
            if tools is None or version(config) in self._errors:
                pending.append(ident)
                continue
            for tool in tools:
                if query.casefold() in (tool["name"] + tool.get("description", "")).casefold():
                    entries.append({"server": ident, "tool": tool["name"],
                                    "description": tool.get("description", "")})
        end = cursor + page_size
        return {"entries": entries[cursor:end], "cursor": cursor,
                "next_cursor": end if end < len(entries) else None,
                "incomplete": bool(pending), "load_servers": pending,
                "servers": self.status(selected)}

    async def describe(self, scope, server, tool):
        tools = await self.load(scope, server)
        return deepcopy(self._tool(tools, tool))

    @staticmethod
    def _tool(tools, name):
        for tool in tools:
            if tool["name"] == name:
                return tool
        raise LogAgentError("mcp_tool_missing", "绑定服务中不存在指定工具", {"tool": name})

    async def call(self, scope, server, tool, arguments, *, context, timeout_seconds=None):
        config = self._bound(scope, server)
        key, phase, raw = version(config), "connect", None
        try:
            async with asyncio.timeout(timeout_seconds or config.timeout):
                async with self.connector.connect(config, context) as session:
                    self._active[key] = self._active.get(key, 0) + 1
                    try:
                        tools = await self._refresh(session, config)
                        phase = "validate"
                        description = self._tool(tools, tool)
                        schema = description["inputSchema"]
                        draft = schema.get("$schema", "https://json-schema.org/draft/2020-12/schema")
                        if draft.rstrip("#") != "https://json-schema.org/draft/2020-12/schema":
                            raise LogAgentError("invalid_schema", "MCP schema 仅支持 JSON Schema 2020-12")
                        validate_instance(arguments, schema)
                        phase = "dispatched"
                        result = await session.call_tool(tool, deepcopy(arguments))
                        raw = result.model_dump(mode="json", by_alias=True, exclude_unset=True)
                        phase = "received"
                        if getattr(session, "catalog_changed", False):
                            await self._refresh(session, config)
                    finally:
                        self._active[key] -= 1
        except asyncio.CancelledError:
            # The owner records cancellation of its dispatched operation; never replay it.
            raise
        except LogAgentError:
            raise
        except Exception as exc:
            self._errors[key] = type(exc).__name__
            if raw is None:
                return MCPExecution(server, tool, dict(context),
                                    "timeout" if isinstance(exc, TimeoutError) else "failed",
                                    phase, phase != "dispatched", error=type(exc).__name__)
            # A confirmed result remains confirmed even if transport cleanup fails.
            return MCPExecution(server, tool, dict(context),
                                "tool_error" if raw.get("isError") else "success",
                                "received", True, raw, "transport_cleanup_failed", count_state(raw))
        return MCPExecution(server, tool, dict(context),
                            "tool_error" if raw.get("isError") else "success", phase, True, raw,
                            count_state=count_state(raw))


def count_state(raw: dict | None) -> str:
    meta = raw.get("_meta") if isinstance(raw, dict) else None
    value = meta.get("logagent_count") if isinstance(meta, dict) else None
    return "available" if type(value) is int and value >= 0 else "count_unavailable"
