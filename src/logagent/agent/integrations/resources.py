"""Capture the published configuration and tool scope once for each turn."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from logagent.agent.config import AgentConfig
from logagent.agent.contracts import SessionView, TurnSnapshot, freeze
from logagent.agent.integrations.mcp import MCPGateway
from logagent.agent.tools.declaration import ToolDeclaration
from logagent.errors import LogAgentError


class ResourceProvider:
    def __init__(self, *, config: AgentConfig, resources=None, plugins=None,
                 declarations=(), default_model=None, ai_config=None,
                 has_model_provider=False, gateway_factory=None, mcp_runtime=None,
                 bindings=None):
        self.config = config
        self.resources = resources
        self.plugins = plugins
        self._declarations = tuple(declarations)
        self.default_model = default_model
        self.ai_config = ai_config
        self.model_provider = has_model_provider
        self.gateway_factory = gateway_factory
        self.mcp_runtime = mcp_runtime
        self.bindings = bindings

    def tool_views(self) -> list[dict[str, Any]]:
        """Return the published tool DTOs used by the next turn."""
        generation = self.plugins.generation if self.plugins is not None else None
        owners = ({item.name: item.plugin for item in self.plugins.toolRegister.describe()}
                  if self.plugins is not None else {})
        views = []
        for item in self._tool_declarations():
            # Registered tool descriptions carry their plugin owner.  Built-ins
            # are represented by their stable plugin IDs even when the service
            # is used without a PluginRegistry in tests or embedded callers.
            owner = owners.get(item.name, f"agent_{item.name}")
            schema = item.input_schema
            views.append({
                "name": item.name,
                "plugin": owner,
                "description": item.description,
                "execution": item.execution,
                "input_schema": schema,
                "definition_tokens": max(1, len(str(schema)) // 4),
                "generation": generation,
                "enabled": True,
            })
        if self.plugins is not None:
            published = {item["plugin"] for item in views}
            for plugin in self.plugins.toolRegister.plugins():
                if plugin["plugin"] not in published:
                    views.append({**plugin, "name": plugin["plugin"].removeprefix("agent_"),
                                  "description": "未注册；启用后显示实际定义", "execution": None,
                                  "input_schema": None, "definition_tokens": 0,
                                  "generation": generation, "registered": False})
        return views

    def _tool_declarations(self, session: SessionView | None = None) -> tuple[ToolDeclaration, ...]:
        """Project the published tool registry into graph declarations."""
        declarations: list[ToolDeclaration] = []
        if self.plugins is None:
            declarations = list(self._declarations)
        else:
            for description in self.plugins.toolRegister.describe():
                tool = self.plugins.toolRegister.get(description.name)
                if tool is None:
                    continue
                declarations.append(ToolDeclaration(
                    tool.name, tool.description, tool.input_schema, tool.execution, tool.invoke,
                ))
        if session is not None and session.tool_names is not None:
            allowed = set(session.tool_names)
            unknown = sorted(allowed - {item.name for item in declarations})
            if unknown:
                raise LogAgentError("tool_unavailable", "Workflow Agent 请求了未注册工具",
                                    {"tools": unknown})
            declarations = [item for item in declarations if item.name in allowed]
        return tuple(declarations)

    def resolve_model(self, selected: str | None, snapshot: dict[str, Any]) -> tuple[Any, str]:
        """Resolve a model reference against one ResourceStore publication.

        A reference can be ``ai:model`` or ``ai/model``. Bare model names are
        accepted only when exactly one AI resource provides that name.
        """
        reference = selected or self.default_model
        candidates = [
            (ai_id, name, config)
            for ai_id, config in snapshot.get("ai", {}).items()
            for name in config.models
        ]
        if reference:
            separator = ":" if ":" in reference else "/" if "/" in reference else None
            if separator is not None:
                ai_id, name = reference.split(separator, 1)
                config = snapshot.get("ai", {}).get(ai_id)
                if config is not None and name in config.models:
                    return config, name
                raise LogAgentError("model_unavailable", "Agent session 引用的模型不可用",
                                    {"model": reference})
            matches = [(name, config) for _, name, config in candidates if name == reference]
            if len(matches) == 1:
                return matches[0][1], matches[0][0]
            if len(matches) > 1:
                raise LogAgentError("model_ambiguous", "模型名称对应多个 AI 资源",
                                    {"model": reference})
            raise LogAgentError("model_unavailable", "Agent session 引用的模型不可用",
                                {"model": reference})
        if len(candidates) == 1:
            return candidates[0][2], candidates[0][1]
        raise LogAgentError("model_unavailable", "Agent session 没有可用模型")

    def capture(self, session: SessionView) -> TurnSnapshot:
        config = freeze(self.config)
        declarations = tuple(replace(item, input_schema=freeze(item.input_schema))
                             for item in self._tool_declarations(session))
        if self.resources is None:
            gateway = (self.gateway_factory(session) if self.gateway_factory is not None else
                       MCPGateway(self.mcp_runtime, self.bindings.read(session.session_id)) if self.mcp_runtime else None)
            return TurnSnapshot(config, freeze(session.ai_config or self.ai_config), session.model,
                                  None, None, None, declarations, gateway)
        snapshot = self.resources.invocation_snapshot()
        ai_config = None
        model_name = session.model
        summary_ai_config = None
        summary_model = None
        if not self.model_provider:
            if session.ai_config is not None:
                ai_config, model_name = session.ai_config, session.model
            else:
                ai_config, model_name = self.resolve_model(session.model, snapshot)
            if config.summary_ai is not None:
                summary_ai_config, summary_model = self.resolve_summary_model(
                    config.summary_ai, model_name, snapshot,
                )
        if self.gateway_factory is not None:
            gateway = self.gateway_factory(session)
        elif self.mcp_runtime is not None:
            gateway = MCPGateway(self.mcp_runtime, self.bindings.read(session.session_id))
        else:
            gateway = None
        return TurnSnapshot(
            config, freeze(ai_config), model_name, freeze(summary_ai_config), summary_model,
            self.plugins.generation if self.plugins is not None else None,
            declarations, gateway,
        )

    @staticmethod
    def resolve_summary_model(reference: str, main_model: str | None,
                               snapshot: dict[str, Any]) -> tuple[Any, str]:
        """Select a model from the configured summary AI resource.

        ``summary_ai`` names an AI resource rather than duplicating a second model
        selector in AgentConfig.  Reuse the main model when that resource exposes
        it; otherwise use its first configured model in stable order.  An empty
        or unknown resource is an explicit configuration error.
        """
        config = snapshot.get("ai", {}).get(reference)
        if config is None:
            raise LogAgentError("model_unavailable", "Agent 摘要模型资源不可用",
                                {"summary_ai": reference})
        if main_model is not None and main_model in config.models:
            return config, main_model
        names = sorted(config.models)
        if not names:
            raise LogAgentError("model_unavailable", "Agent 摘要模型资源没有可用模型",
                                {"summary_ai": reference})
        return config, names[0]
