"""Compile the Agent's LangGraph with one turn context and tool boundary."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.utils.function_calling import convert_to_openai_tool

from logagent.agent.context.compaction import ContextMiddleware
from logagent.agent.ports import ToolDeclarationPort
from logagent.agent.runtime.context import AgentContext
from logagent.agent.runtime.state import AgentState
from logagent.agent.tools.langchain import build_tools
from logagent.redaction import redact_text


def create_graph(*, model, declarations: Iterable[ToolDeclarationPort], context: AgentContext,
                 system_prompt: str, checkpointer=None, use_summarization: bool = True,
                 summary_model=None, summary_timeout: float | None = None):
    """Compile a graph for a frozen turn and its leased model dependencies."""
    declarations = tuple(declarations)
    tools = build_tools(declarations)
    middleware = []
    if use_summarization:
        async def record_compaction(data):
            path = f"History/{context.session_id}/summaries/{uuid4().hex}.md"
            await context.workspace.save_runtime(
                path, redact_text(data["summary"]).encode("utf-8"),
            )
            await context.event_log.append(
                "context.compacted", turn_id=context.turn_id, artifact_path=path,
                source_event_range={"start": 1, "end": context.event_log.events[-1]["id"]},
                **data,
            )

        async def record_budget(data):
            await context.event_log.append("context.budget", turn_id=context.turn_id, **data)

        context.scope.context_middleware = ContextMiddleware(
            model=model, config=context.config, system_prompt=system_prompt,
            tools=[convert_to_openai_tool(tool) for tool in tools],
            summary_model=summary_model, summary_timeout=summary_timeout,
            on_compacted=record_compaction, on_budget=record_budget,
            on_boundary=context.on_boundary,
        )
        middleware.append(context.scope.context_middleware)
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware,
        state_schema=AgentState,
        context_schema=AgentContext,
        checkpointer=checkpointer,
        name="logagent-agent",
    )


__all__ = ["create_graph"]
