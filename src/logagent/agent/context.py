"""Captured prompt prefix and complete request budgets around official compaction."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware, SummarizationMiddleware, hook_config
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph.message import add_messages

from logagent.agent.config import AgentConfig
from logagent.errors import LogAgentError

RUNTIME_INSTRUCTION = (
    "运行时文件入口固定为 Runtime/self.json。需要了解当前会话、分支、轮次、来源和工具代次时，"
    "请使用 read 读取该文件；它是只读会话映射，不要写入或通过 grep 搜索。"
)


class TokenCounter:
    """Use a model tokenizer when supported; explicitly label the fallback."""

    def __init__(self, model=None):
        self.model = model
        self.source = "model_tokenizer"

    def __call__(self, messages) -> int:
        if not messages:
            return 0
        counter = getattr(self.model, "get_num_tokens_from_messages", None)
        implementation = getattr(type(self.model), "get_num_tokens_from_messages", None)
        if counter is not None and implementation is not BaseChatModel.get_num_tokens_from_messages:
            try:
                return counter(messages)
            except (NotImplementedError, ImportError):
                # Unsupported tokenizer/model, not an upstream invocation error.
                pass
        self.source = "framework_approximate"
        return count_tokens_approximately(messages)


def token_count(messages) -> int:
    return count_tokens_approximately(messages)


def context_window(configured: int | None, model=None) -> int:
    profile = getattr(model, "profile", None)
    known = profile.get("max_input_tokens") if isinstance(profile, dict) else None
    if type(known) is not int or known <= 0:
        known = None
    if configured is None and known is None:
        raise LogAgentError("context_budget_unavailable", "模型容量未知，必须显式配置上下文容量")
    return min(configured, known) if configured and known else configured or known


@dataclass(frozen=True, slots=True)
class ContextBudget:
    window: int
    trigger: int
    keep: int
    output: int

    @classmethod
    def from_config(cls, config: AgentConfig, model=None) -> ContextBudget:
        return cls(context_window(config.context_window, model), config.trigger_tokens,
                   config.keep_tokens, config.output_tokens)


def build_system_prompt(*, agents: str, session_id: str, branch_id: str,
                        turn_id: str, workspace: str, workflow_session_id: str | None,
                        now: datetime) -> str:
    source = workflow_session_id or "none"
    runtime = (
        f"session={session_id}; branch={branch_id}; turn={turn_id}; "
        f"workflow_session={source}; date={now.date().isoformat()}; workspace={workspace}"
    )
    return f"{RUNTIME_INSTRUCTION}\n运行上下文：{runtime}\n\n工作区常驻规则：\n{agents}".strip()


def estimate_request(messages: list[BaseMessage], system_prompt: str, tools: list[dict[str, Any]],
                     config: AgentConfig, *, model=None) -> dict[str, Any]:
    counter = TokenCounter(model)
    budget = ContextBudget.from_config(config, model)
    return _estimate(messages, system_prompt, tools, budget, counter)


def _estimate(messages, system_prompt, tools, budget, counter) -> dict[str, Any]:
    body = counter(messages)
    stable = counter([SystemMessage(content=system_prompt)]) if system_prompt else 0
    definitions = counter([HumanMessage(content=json.dumps(
        tools, ensure_ascii=False, separators=(",", ":"),
    ))]) if tools else 0
    total = body + stable + definitions + budget.output
    return {"messages": body, "system": stable, "tools": definitions,
            "output": budget.output, "total": total, "window": budget.window,
            "remaining": budget.window - total, "estimated": True,
            "token_counter": counter.source}


def _validate_usage(usage, *, summary=False) -> None:
    if usage["total"] > usage["window"]:
        code = "summary_context_budget_exceeded" if summary else "context_budget_exceeded"
        raise LogAgentError(code, "完整请求与输出预留超过模型上下文容量", usage)


def validate_request_budget(messages: list[BaseMessage], system_prompt: str,
                            tools: list[dict[str, Any]], config: AgentConfig,
                            *, model=None) -> dict[str, Any]:
    usage = estimate_request(messages, system_prompt, tools, config, model=model)
    _validate_usage(usage)
    return usage


class _SummaryInvocation:
    """Check the official middleware's exact serialized prompt before any I/O."""

    def __init__(self, model, *, config, timeout, same_model):
        self.model = model
        self.config = config
        self.timeout = timeout
        self.same_model = same_model

    def __getattr__(self, name):
        return getattr(self.model, name)

    def with_retry(self, *_args, **_kwargs):
        # Capacity errors cannot become framework retries. A summary call also
        # must remain inside its own AI resource timeout.
        return self

    async def ainvoke(self, input, config=None, **kwargs):
        configured = self.config.summary_context_window
        if configured is None and self.same_model:
            configured = self.config.context_window
        budget = ContextBudget(context_window(configured, self.model), 0, 0,
                               self.config.summary_max_tokens)
        usage = _estimate([HumanMessage(content=input)], "", [], budget, TokenCounter(self.model))
        _validate_usage(usage, summary=True)
        async with asyncio.timeout(self.timeout):
            response = await self.model.ainvoke(input, config=config, **kwargs)
        if not response.text.strip():
            raise LogAgentError("context_compaction_failed", "摘要模型返回空摘要")
        return response


def summarization_middleware(model, config: AgentConfig, *, summary_prompt: str | None = None,
                             summary_timeout: float | None = None,
                             trigger_tokens: int | None = None, token_counter=None,
                             same_model: bool = True):
    """Create one official middleware, retaining the complete selected prefix."""
    prompt = summary_prompt if summary_prompt is not None else config.summary_prompt
    if "{messages}" not in prompt:
        prompt = prompt.rstrip() + "\n\n<messages>\n{messages}\n</messages>"
    invocation = _SummaryInvocation(model, config=config, timeout=summary_timeout,
                                    same_model=same_model)
    return SummarizationMiddleware(
        invocation,
        trigger=("tokens", trigger_tokens or config.trigger_tokens),
        keep=("tokens", config.keep_tokens),
        token_counter=token_counter or TokenCounter(model),
        summary_prompt=prompt,
        trim_tokens_to_summarize=None,
    )


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


CompactionCallback = Callable[[dict[str, Any]], Awaitable[None]]


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
        # ToolNode must finish the entire group before accepting a new human
        # message or summarizing paired tool calls and receipts.
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
            # The official counter sees only messages. Subtract the immutable
            # envelope, and preselect here so historical reported usage cannot
            # unexpectedly trigger an extra summary.
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
