"""Per-turn prompt assembly and fixed context-budget policy."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import BaseMessage
from langchain_core.messages.utils import count_tokens_approximately

from logagent.agent.config import AgentConfig
from logagent.errors import LogAgentError

RUNTIME_INSTRUCTION = (
    "运行时文件入口固定为 Runtime/self.json。需要了解当前会话、分支、轮次、来源和工具代次时，"
    "请使用 read 读取该文件；它是只读会话映射，不要写入或通过 grep 搜索。"
)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    window: int
    trigger: int
    keep: int
    output: int
    safety: int

    @classmethod
    def from_config(cls, config: AgentConfig) -> ContextBudget:
        if config.context_window is None:
            raise ValueError("Agent context_window must be configured before model execution")
        window = config.context_window
        safety = max(1, int(window * config.safety_ratio))
        return cls(window, int(window * config.trigger_ratio),
                   int(window * config.keep_ratio), config.output_tokens, safety)


def token_count(messages: list[BaseMessage] | tuple[BaseMessage, ...]) -> int:
    return count_tokens_approximately(messages)


def build_system_prompt(*, agents: str, session_id: str, branch_id: str,
                        turn_id: str, workspace: str, workflow_session_id: str | None,
                        now: datetime) -> str:
    source = workflow_session_id or "none"
    runtime = (
        f"session={session_id}; branch={branch_id}; turn={turn_id}; "
        f"workflow_session={source}; date={now.date().isoformat()}; workspace={workspace}"
    )
    return f"{RUNTIME_INSTRUCTION}\n运行上下文：{runtime}\n\n工作区常驻规则：\n{agents}".strip()


def summarization_middleware(model, config: AgentConfig, *, summary_prompt: str | None = None):
    """Create a fresh official middleware for one graph/request.

    The middleware is intentionally not shared between sessions: its model and
    trigger are part of the captured turn snapshot.
    """
    budget = ContextBudget.from_config(config)
    prompt = summary_prompt or config.summary_prompt
    if "{messages}" not in prompt:
        prompt = prompt.rstrip() + "\n\n<messages>\n{messages}\n</messages>"
    return SummarizationMiddleware(
        model,
        trigger=("tokens", budget.trigger),
        keep=("tokens", budget.keep),
        summary_prompt=prompt,
        trim_tokens_to_summarize=None,
    )


def estimate_request(messages: list[BaseMessage], system_prompt: str, tools: list[dict[str, Any]],
                     config: AgentConfig) -> dict[str, int]:
    body = token_count(messages)
    stable = count_tokens_approximately([system_prompt])
    tool_tokens = count_tokens_approximately([str(tool) for tool in tools])
    budget = ContextBudget.from_config(config)
    return {"messages": body, "system": stable, "tools": tool_tokens,
            "total": body + stable + tool_tokens + budget.output,
            "window": budget.window, "remaining": budget.window - body - stable - tool_tokens}


def validate_request_budget(messages: list[BaseMessage], system_prompt: str,
                            tools: list[dict[str, Any]], config: AgentConfig) -> dict[str, int] | None:
    """Validate the complete request envelope before invoking the model."""
    if config.context_window is None:
        raise LogAgentError(
            "context_budget_unavailable", "必须显式配置模型上下文容量后才能执行 Agent",
        )
    usage = estimate_request(messages, system_prompt, tools, config)
    if usage["total"] > usage["window"]:
        raise LogAgentError("context_budget_exceeded", "当前请求超过已配置模型上下文容量", usage)
    return usage


def _validate_tool_pairs(messages: list[BaseMessage]) -> None:
    pending = {call["id"] for message in messages
               for call in getattr(message, "tool_calls", []) if "id" in call}
    for message in messages:
        tool_id = getattr(message, "tool_call_id", None)
        if tool_id is not None:
            pending.discard(tool_id)
    if pending:
        raise LogAgentError("context_tool_pairing", "摘要后存在未配对的工具调用", {"tool_calls": sorted(pending)})


async def summarize_once(model, messages: list[BaseMessage], config: AgentConfig) -> list[BaseMessage]:
    """Delegate one complete prefix to the public LangChain middleware API."""
    middleware = summarization_middleware(model, config)
    state = {"messages": deepcopy(messages)}
    result = await middleware.abefore_model(state, None)
    if result is None:
        return messages
    compacted = result.get("messages", messages)
    if not isinstance(compacted, list):
        raise LogAgentError("context_compaction_failed", "摘要模型返回了无效消息状态")
    _validate_tool_pairs(compacted)
    return compacted
