"""LangGraph Agent assembly and the single tool execution boundary."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import StructuredTool

from logagent.agent.artifacts import ArtifactStore
from logagent.agent.builtin.declaration import ToolDeclaration
from logagent.agent.config import AgentConfig
from logagent.agent.context import summarization_middleware
from logagent.agent.events import EventLog
from logagent.agent.scheduling import ToolScheduler
from logagent.errors import LogAgentError


@dataclass(slots=True)
class AgentToolContext:
    workspace: Any
    sandbox: Any
    gateway: Any
    config: AgentConfig
    session_id: str
    turn_id: str
    branch_id: str
    event_log: EventLog
    scheduler: ToolScheduler
    artifacts: ArtifactStore | None = None
    tool_call_id: str | None = None
    tool_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    ordinals: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def _tool_error(error: LogAgentError) -> dict[str, Any]:
    return {"status": "failed", "error": error.info.model_dump(mode="json")}


def _langchain_tool(declaration: ToolDeclaration, context: AgentToolContext) -> StructuredTool:
    async def invoke(**arguments):
        ordinal = context.ordinals[declaration.name]
        context.ordinals[declaration.name] += 1
        key = f"{context.turn_id}:{declaration.name}:{ordinal}"
        reservation = await context.event_log.reserve_tool(key, arguments)
        if reservation.status == "tool.completed":
            return reservation.result or {}
        existing = context.tool_tasks.get(key)
        if existing is not None:
            return await asyncio.shield(existing)

        async def execute():
            async with context.scheduler.acquire(declaration.execution):
                try:
                    result = await declaration.invoke(
                        arguments, replace(context, tool_call_id=key)
                    )
                    if not isinstance(result, dict):
                        result = {"status": "success", "value": result}
                    await context.event_log.complete_tool(key, arguments, result)
                    return result
                except asyncio.CancelledError:
                    await context.event_log.mark_unknown(key, arguments, reason="cancelled")
                    raise
                except LogAgentError as error:
                    result = _tool_error(error)
                    await context.event_log.complete_tool(key, arguments, result)
                    return result

        task = asyncio.create_task(execute(), name=f"agent:tool:{declaration.name}")
        context.tool_tasks[key] = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                context.tool_tasks.pop(key, None)

    return StructuredTool.from_function(
        coroutine=invoke,
        name=declaration.name,
        description=declaration.description,
        args_schema=declaration.input_schema,
        infer_schema=False,
    )


def create_graph(*, model, declarations: Iterable[ToolDeclaration], context: AgentToolContext,
                 system_prompt: str, checkpointer=None, use_summarization: bool = True):
    tools = [_langchain_tool(declaration, context) for declaration in declarations]
    middleware = []
    if use_summarization and context.config.context_window is not None:
        middleware.append(summarization_middleware(model, context.config))
    return create_agent(model=model, tools=tools, system_prompt=system_prompt,
                        middleware=middleware, checkpointer=checkpointer,
                        name="logagent-agent")


def tool_definitions(declarations: Iterable[ToolDeclaration]) -> list[dict[str, Any]]:
    return [{"name": item.name, "description": item.description, "input_schema": item.input_schema,
             "execution": item.execution} for item in declarations]
