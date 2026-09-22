"""LangGraph Agent assembly and the single tool execution boundary."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain_core.tools import InjectedToolArg, StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime

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
    async def invoke(runtime: Annotated[ToolRuntime, InjectedToolArg], **arguments):
        tool_call_id = runtime.tool_call_id
        if not tool_call_id:
            # A manually invoked tool may not have a ToolNode runtime.  Keep a
            # deterministic fallback for that boundary while model calls use
            # their actual tool_call_id below.
            ordinal = context.ordinals[declaration.name]
            context.ordinals[declaration.name] += 1
            tool_call_id = f"{declaration.name}:{ordinal}"
        key = f"{context.session_id}:{context.turn_id}:{tool_call_id}"
        reservation = await context.event_log.reserve_tool(key, arguments)
        if reservation.status == "tool.completed":
            return reservation.result or {}
        existing = context.tool_tasks.get(key)
        if existing is not None:
            return await asyncio.shield(existing)
        if reservation.status == "active":
            # The owner may live in another service process.  Re-read the
            # durable event log until it publishes a terminal result; never
            # execute a side effect a second time merely because this worker
            # cannot see the owner's in-memory task.
            completed = await context.event_log.wait_for_tool(key, arguments)
            return completed.result or {}

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
