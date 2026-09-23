"""LangGraph Agent assembly and the single tool execution boundary."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from time import monotonic
from typing import Annotated, Any
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.tools import InjectedToolArg, StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.prebuilt.tool_node import ToolRuntime

from logagent.agent.artifacts import ArtifactStore
from logagent.agent.builtin.declaration import ToolDeclaration
from logagent.agent.config import AgentConfig
from logagent.agent.context import ContextMiddleware
from logagent.agent.events import EventLog
from logagent.agent.scheduling import ToolScheduler
from logagent.errors import LogAgentError
from logagent.models import CollectionContext
from logagent.redaction import redact_data, redact_text


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
    collection: CollectionContext | None = None
    tool_call_id: str | None = None
    read_enabled: bool = True
    on_boundary: Any = None
    context_middleware: ContextMiddleware | None = None
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
        existing = context.tool_tasks.get(key)
        if existing is not None:
            return await asyncio.shield(existing)

        async def execute():
            started = False
            began = monotonic()
            metadata = {"turn_id": context.turn_id, "tool_call_id": tool_call_id,
                        "name": declaration.name, "arguments": redact_data(arguments)}
            try:
                execution = (context.gateway.execution(arguments)
                             if declaration.name == "plugin" and context.gateway is not None
                             else declaration.execution)
                metadata["execution"] = execution
                await context.event_log.append("tool.queued", tool_key=key, **metadata)
                async with context.scheduler.acquire(execution):
                    reservation = await context.event_log.reserve_tool(key, arguments, **metadata)
                    if reservation.status in {"tool.completed", "tool.outcome_unknown"}:
                        return reservation.result or {}
                    if reservation.status == "active":
                        completed = await context.event_log.wait_for_tool(key, arguments)
                        return completed.result or {}
                    started = True
                    try:
                        result = await declaration.invoke(arguments, replace(context, tool_call_id=key))
                    except Exception as error:
                        result = (_tool_error(error) if isinstance(error, LogAgentError) else
                                  {"status": "failed", "error": {"code": "tool_failed",
                                   "message": redact_text(str(error)), "type": type(error).__name__}})
                        if not isinstance(error, LogAgentError):
                            await context.event_log.complete_tool(key, arguments, result)
                            raise
                    if not isinstance(result, dict):
                        result = {"status": "success", "value": result}
                    if context.artifacts is not None:
                        result = await context.artifacts.save(
                            result, session_id=context.session_id, turn_id=context.turn_id,
                            tool_call_id=tool_call_id, config=context.config,
                            count_tokens=lambda text: count_tokens_approximately([HumanMessage(content=text)]),
                            schema_output=declaration.name == "plugin" and arguments.get("action") == "schema",
                            read_enabled=context.read_enabled,
                        )
                    result["duration_ms"] = round((monotonic() - began) * 1000)
                    await context.event_log.complete_tool(key, arguments, result)
                    return result
            except asyncio.CancelledError:
                if started:
                    await context.event_log.mark_unknown(key, arguments, reason="cancelled")
                else:
                    await context.event_log.append(
                        "tool.completed", tool_key=key, result={"status": "cancelled"}, **metadata,
                    )
                raise
            except LogAgentError as error:
                if error.code in {"event_log_corrupt", "tool_key_conflict"}:
                    raise
                result = _tool_error(error)
                if started:
                    await context.event_log.complete_tool(key, arguments, result)
                else:
                    await context.event_log.append("tool.completed", tool_key=key, result=result, **metadata)
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
                 system_prompt: str, checkpointer=None, use_summarization: bool = True,
                 summary_model=None, summary_timeout: float | None = None):
    """Assemble one turn graph with an optional independently leased summary model.

    ``summary_model`` is deliberately passed as an already leased dependency.  The
    graph never resolves resources or opens a second connection, which keeps the
    main model lease and the optional summary lease visible to ``AgentService``.
    """
    tools = [_langchain_tool(declaration, context) for declaration in declarations]
    middleware = []
    if use_summarization:
        async def record_compaction(data):
            path = f"History/{context.session_id}/summaries/{uuid4().hex}.md"
            await context.workspace.save_runtime(path, redact_text(data["summary"]).encode("utf-8"))
            await context.event_log.append(
                "context.compacted", turn_id=context.turn_id, artifact_path=path,
                source_event_range={"start": 1, "end": context.event_log.events[-1]["id"]},
                **data,
            )

        async def record_budget(data):
            await context.event_log.append("context.budget", turn_id=context.turn_id, **data)

        context.context_middleware = ContextMiddleware(
            model=model, config=context.config, system_prompt=system_prompt,
            tools=[convert_to_openai_tool(tool) for tool in tools],
            summary_model=summary_model, summary_timeout=summary_timeout,
            on_compacted=record_compaction, on_budget=record_budget,
            on_boundary=context.on_boundary,
        )
        middleware.append(context.context_middleware)
    return create_agent(model=model, tools=tools, system_prompt=system_prompt,
                        middleware=middleware, checkpointer=checkpointer,
                        name="logagent-agent")


def tool_definitions(declarations: Iterable[ToolDeclaration]) -> list[dict[str, Any]]:
    return [{"name": item.name, "description": item.description, "input_schema": item.input_schema,
             "execution": item.execution} for item in declarations]
