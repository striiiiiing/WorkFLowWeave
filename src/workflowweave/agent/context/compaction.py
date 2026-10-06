"""Agent message compaction and command boundaries around model calls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import BaseMessage, RemoveMessage, SystemMessage
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime
from langgraph.types import Command

from workflowweave.agent.config import AgentConfig
from workflowweave.agent.context.budget import (
    ContextBudget,
    TokenCounter,
    _estimate,
    _validate_usage,
    summarization_middleware,
)
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.redaction import redact_text


def _validate_tool_pairs(messages: list[BaseMessage]) -> None:
    pending: set[str] = set()
    for message in messages:
        if isinstance(message, RemoveMessage):
            continue
        tool_id = getattr(message, "tool_call_id", None)
        if tool_id is not None:
            if tool_id not in pending:
                raise WorkFLowWeaveError("context_tool_pairing", "摘要后存在孤立工具结果",
                                    {"tool_call_id": tool_id})
            pending.remove(tool_id)
            continue
        if pending:
            raise WorkFLowWeaveError("context_tool_pairing", "摘要后存在未配对的工具调用",
                                {"tool_calls": sorted(pending)})
        pending.update(call["id"] for call in getattr(message, "tool_calls", []))
    if pending:
        raise WorkFLowWeaveError("context_tool_pairing", "摘要后存在未配对的工具调用",
                            {"tool_calls": sorted(pending)})


CompactionCallback = Callable[[dict], Awaitable[None]]


class ContextMiddleware(AgentMiddleware):
    """Own the complete envelope policy while delegating message selection."""

    def __init__(self, *, model, config, system_prompt, tools, summary_model=None,
                 summary_timeout=None, on_compacted: CompactionCallback | None = None,
                 on_budget: CompactionCallback | None = None, on_boundary=None):
        self.config = config
        self.system_prompt = system_prompt
        self.tool_definitions = tools
        self.model = model
        self.summary_model = summary_model if summary_model is not None else model
        self.summary_timeout = summary_timeout
        self.on_compacted = on_compacted
        self.on_budget = on_budget
        self.budget = ContextBudget.from_config(config, model)
        self.counter = TokenCounter(model)
        self.on_boundary = on_boundary
        self.model_returned = False

    def estimate(self, messages):
        return self._estimate(messages)

    @staticmethod
    def _context(runtime: Runtime | None) -> Any:
        return getattr(runtime, "context", None) if runtime is not None else None

    def _scope_value(self, runtime, name, fallback):
        context = self._context(runtime)
        scope = getattr(context, "scope", None)
        value = getattr(scope, name, None) if scope is not None else None
        return fallback if value is None else value

    def _scope_tools(self, runtime):
        allowed = self._scope_value(runtime, "allowed_tool_names", None)
        if allowed is None:
            return self.tool_definitions
        return [tool for tool in self.tool_definitions
                if tool.get("function", {}).get("name") in allowed
                or tool.get("name") in allowed]

    def _estimate(self, messages, runtime=None):
        model = self._scope_value(runtime, "model", self.model)
        context = self._context(runtime)
        config = getattr(context, "config", self.config)
        return _estimate(
            messages,
            self._scope_value(runtime, "system_prompt", self.system_prompt),
            self._scope_tools(runtime),
            ContextBudget.from_config(config, model),
            TokenCounter(model),
        )

    async def awrap_model_call(self, request, handler):
        model = self._scope_value(request.runtime, "model", self.model)
        prompt = self._scope_value(request.runtime, "system_prompt", self.system_prompt)
        allowed = self._scope_value(request.runtime, "allowed_tool_names", None)
        tools = request.tools
        if allowed is not None:
            tools = [tool for tool in tools if getattr(tool, "name", None) in allowed]
        return await handler(request.override(
            model=model,
            system_message=SystemMessage(content=prompt) if prompt else None,
            tools=tools,
        ))

    async def abefore_model(self, state, runtime):
        context = self._context(runtime)
        returned = bool(getattr(context.scope, "model_returned", False)) if context else False
        if context:
            context.scope.model_returned = False
        update = await self._commands(state["messages"], runtime) if returned else None
        if update is not None:
            return update
        return await self.prepare(state["messages"], runtime)

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime):
        context = self._context(runtime)
        if context:
            context.scope.model_returned = True
        if getattr(state["messages"][-1], "tool_calls", None):
            return None
        return await self._commands(state["messages"], runtime, final=True)

    async def _commands(self, messages, runtime, *, final=False):
        boundary = getattr(self._context(runtime), "on_boundary", None) or self.on_boundary
        if boundary is None:
            return None
        batch = await boundary(final=final)
        if batch is None:
            return None
        additions, force, complete = batch
        combined = add_messages(messages, additions)
        try:
            result = await self.prepare(combined, runtime, force=force)
        except (Exception, asyncio.CancelledError) as exc:
            await complete(compacted=False, error={"type": type(exc).__name__, "message": str(exc)})
            raise
        await complete(compacted=result is not None)
        update = result or ({"messages": additions} if additions else {})
        if not update:
            return None
        return Command(update=update, goto="model" if additions and final else ())

    async def prepare(self, messages, runtime=None, *, force=False):
        usage = self._estimate(messages, runtime)
        result = None
        context = self._context(runtime)
        config = getattr(context, "config", self.config)
        model = self._scope_value(runtime, "model", self.model)
        budget = ContextBudget.from_config(config, model)
        summary_model = self._scope_value(runtime, "summary_model", self.summary_model)
        summary_timeout = self._scope_value(runtime, "summary_timeout", self.summary_timeout)
        if force or usage["total"] >= min(budget.trigger, budget.window):
            trigger = max(1, min(budget.trigger, budget.window)
                          - usage["system"] - usage["tools"] - usage["output"])
            middleware = summarization_middleware(
                summary_model, config, summary_timeout=summary_timeout,
                trigger_tokens=1 if force else trigger, token_counter=TokenCounter(model),
                same_model=config.summary_ai is None,
            )
            result = await middleware.abefore_model({"messages": deepcopy(messages)}, runtime)
        compacted = add_messages([], result["messages"]) if result else messages
        _validate_tool_pairs(compacted)
        after = self._estimate(compacted, runtime)
        _validate_usage(after)
        if result and self.on_compacted is not None:
            retained = {message.id for message in compacted}
            await self.on_compacted({
                "summary": compacted[0].content,
                "removed_message_ids": [message.id for message in messages
                                        if message.id not in retained],
                "before": usage, "after": after,
            })
        elif result and context is not None:
            retained = {message.id for message in compacted}
            path = f"History/{context.session_id}/summaries/{uuid4().hex}.md"
            await context.workspace.save_runtime(
                path,
                redact_text(str(compacted[0].content)).encode("utf-8"),
            )
            await context.event_log.append(
                "context.compacted", turn_id=context.turn_id,
                artifact_path=path,
                source_event_range={"start": 1, "end": context.event_log.events[-1]["id"]},
                summary=compacted[0].content,
                removed_message_ids=[message.id for message in messages if message.id not in retained],
                before=usage, after=after,
            )
        if self.on_budget is not None:
            await self.on_budget(after)
        elif context is not None:
            await context.event_log.append("context.budget", turn_id=context.turn_id, **after)
        return result


async def summarize_once(model, messages: list[BaseMessage], config: AgentConfig) -> list[BaseMessage]:
    """Run the same checked compaction policy used before every graph request."""
    middleware = ContextMiddleware(model=model, config=config, system_prompt="", tools=[])
    result = await middleware.prepare(messages)
    return add_messages([], result["messages"]) if result else messages
