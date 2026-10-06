"""Complete Agent prompt and output token budget calculations."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately

from workflowweave.agent.config import AgentConfig
from workflowweave.errors import WorkFLowWeaveError


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
        raise WorkFLowWeaveError("context_budget_unavailable", "模型容量未知，必须显式配置上下文容量")
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


def estimate_request(messages: list, system_prompt: str, tools: list[dict[str, Any]],
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
            "trigger": min(budget.trigger, budget.window),
            "remaining": budget.window - total, "estimated": True,
            "token_counter": counter.source}


def _validate_usage(usage, *, summary=False) -> None:
    if usage["total"] > usage["window"]:
        code = "summary_context_budget_exceeded" if summary else "context_budget_exceeded"
        raise WorkFLowWeaveError(code, "完整请求与输出预留超过模型上下文容量", usage)


def validate_request_budget(messages: list, system_prompt: str,
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
        # Capacity errors cannot become framework retries.
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
            raise WorkFLowWeaveError("context_compaction_failed", "摘要模型返回空摘要")
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
