"""Agent message compaction and command boundaries around model calls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import BaseMessage, RemoveMessage
from langgraph.graph.message import add_messages

from logagent.agent.config import AgentConfig
from logagent.agent.context.budget import (
    ContextBudget,
    TokenCounter,
    _estimate,
    _validate_usage,
    summarization_middleware,
)
from logagent.errors import LogAgentError


def _validate_tool_pairs(messages: list[BaseMessage]) -> None:
    pending: set[str] = set()
    for message in messages:
        if isinstance(message, RemoveMessage):
            continue
        tool_id = getattr(message, "tool_call_id", None)
        if tool_id is not None:
            if tool_id not in pending:
                raise LogAgentError("context_tool_pairing", "摘要后存在孤立工具结果",
                                    {"tool_call_id": tool_id})
            pending.remove(tool_id)
            continue
        if pending:
            raise LogAgentError("context_tool_pairing", "摘要后存在未配对的工具调用",
                                {"tool_calls": sorted(pending)})
        pending.update(call["id"] for call in getattr(message, "tool_calls", []))
    if pending:
        raise LogAgentError("context_tool_pairing", "摘要后存在未配对的工具调用",
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
        return _estimate(messages, self.system_prompt, self.tool_definitions,
                         self.budget, self.counter)

    async def abefore_model(self, state, runtime):
        update = await self._commands(state["messages"], runtime) if self.model_returned else None
        self.model_returned = False
        if update is not None:
            return update
        return await self.prepare(state["messages"], runtime)

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime):
        self.model_returned = True
        if getattr(state["messages"][-1], "tool_calls", None):
            return None
        return await self._commands(state["messages"], runtime, final=True)

    async def _commands(self, messages, runtime, *, final=False):
        if self.on_boundary is None:
            return None
        batch = await self.on_boundary(final=final)
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
        if additions and final:
            update["jump_to"] = "model"
        return update

    async def prepare(self, messages, runtime=None, *, force=False):
        usage = self.estimate(messages)
        result = None
        if force or usage["total"] >= min(self.budget.trigger, self.budget.window):
            trigger = max(1, min(self.budget.trigger, self.budget.window)
                          - usage["system"] - usage["tools"] - usage["output"])
            middleware = summarization_middleware(
                self.summary_model, self.config, summary_timeout=self.summary_timeout,
                trigger_tokens=1 if force else trigger, token_counter=self.counter,
                same_model=self.config.summary_ai is None,
            )
            result = await middleware.abefore_model({"messages": deepcopy(messages)}, runtime)
        compacted = add_messages([], result["messages"]) if result else messages
        _validate_tool_pairs(compacted)
        after = self.estimate(compacted)
        _validate_usage(after)
        if result and self.on_compacted is not None:
            retained = {message.id for message in compacted}
            await self.on_compacted({
                "summary": compacted[0].content,
                "removed_message_ids": [message.id for message in messages
                                        if message.id not in retained],
                "before": usage, "after": after,
            })
        if self.on_budget is not None:
            await self.on_budget(after)
        return result


async def summarize_once(model, messages: list[BaseMessage], config: AgentConfig) -> list[BaseMessage]:
    """Run the same checked compaction policy used before every graph request."""
    middleware = ContextMiddleware(model=model, config=config, system_prompt="", tools=[])
    result = await middleware.prepare(messages)
    return add_messages([], result["messages"]) if result else messages
