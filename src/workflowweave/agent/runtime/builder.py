"""Build one static LangGraph topology and inject turn values at runtime."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from langchain.agents import create_agent
from langchain_core.utils.function_calling import convert_to_openai_tool

from workflowweave.agent.context.compaction import ContextMiddleware
from workflowweave.agent.ports import ToolDeclarationPort
from workflowweave.agent.runtime.context import AgentContext
from workflowweave.agent.runtime.state import AgentState
from workflowweave.agent.tools.langchain import build_tools
from workflowweave.errors import WorkFLowWeaveError


def _declaration_key(declarations: tuple[ToolDeclarationPort, ...]) -> tuple:
    return tuple((item.name, item.description, repr(item.input_schema), item.execution)
                 for item in declarations)


class GraphBuilder:
    """Own the single compiled graph for one checkpointer and tool registry."""

    def __init__(self):
        self._graph: Any = None
        self._middleware: ContextMiddleware | None = None
        self._declarations: tuple | None = None
        self._generation: int | None = None
        self._checkpointer: Any = None

    @property
    def graph(self):
        """The compiled topology, if the application root has initialized it."""
        return self._graph

    @property
    def generation(self):
        return self._generation

    def bind(self, *, context: AgentContext, generation: int | None = None):
        """Bind a turn to the already compiled topology.

        Compilation belongs to the application composition root.  A turn may
        only fail when the published registry generation no longer matches;
        rebuilding is an admission/lifecycle operation, never a turn concern.
        """
        if self._graph is None:
            raise WorkFLowWeaveError("graph_uninitialized", "Agent graph 尚未由组合根初始化")
        if self._generation != generation:
            raise WorkFLowWeaveError(
                "graph_rebuild_required", "Agent 工具 registry 已变化，需要在轮次边界重建 graph",
                {"expected_generation": self._generation, "actual_generation": generation},
            )
        context.scope.context_middleware = self._middleware
        return self._graph

    def build(self, *, model, declarations: Iterable[ToolDeclarationPort], context: AgentContext,
              checkpointer=None, use_summarization: bool = True, generation: int | None = None):
        declarations = tuple(declarations)
        declaration_key = _declaration_key(declarations)
        if self._graph is not None:
            if self._checkpointer is not checkpointer:
                raise WorkFLowWeaveError("graph_rebuild_required", "Agent graph 的 checkpointer 已改变")
            if self._declarations == declaration_key and self._generation == generation:
                context.scope.context_middleware = self._middleware
                return self._graph
            # A new published tool generation is compiled between turns. The
            # coordinator owns admission, so no active turn can observe a
            # partially replaced graph.
            self._graph = None
            self._middleware = None

        tools = build_tools(tuple(deepcopy(item) for item in declarations))
        middleware = ContextMiddleware(
            model=model, config=context.config, system_prompt="",
            tools=[deepcopy(convert_to_openai_tool(tool)) for tool in tools], summary_model=model,
        )
        self._graph = create_agent(
            model=model,
            tools=tools,
            system_prompt=None,
            middleware=[middleware] if use_summarization else [],
            state_schema=AgentState,
            context_schema=AgentContext,
            checkpointer=checkpointer,
            name="workflowweave-agent",
        )
        self._middleware = middleware
        self._declarations = declaration_key
        self._generation = generation
        self._checkpointer = checkpointer
        context.scope.context_middleware = middleware
        return self._graph

    def build_static(self, *, declarations: Iterable[ToolDeclarationPort], config,
                     checkpointer=None, generation: int | None = None):
        """Compile the topology before the first turn; model values arrive via Runtime."""
        bootstrap_config = config
        class _RuntimeModel:
            profile = {"max_input_tokens": bootstrap_config.context_window or 200_000}

            def bind_tools(self, tools, **kwargs):
                return self

        class _Bootstrap:
            config = bootstrap_config
            scope = type("Scope", (), {})()

        return self.build(
            model=_RuntimeModel(), declarations=declarations,
            context=type("Context", (), {"config": config, "scope": _Bootstrap.scope})(),
            checkpointer=checkpointer, generation=generation,
        )


__all__ = ["GraphBuilder"]
