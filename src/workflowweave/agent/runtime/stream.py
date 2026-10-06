"""Run the graph once with a stable thread config and persist its stream."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from workflowweave.agent.runtime.context import AgentContext
from workflowweave.errors import WorkFLowWeaveError


def runnable_config(*, session_id: str, turn_id: str, branch_id: str) -> RunnableConfig:
    """Return the single LangGraph thread configuration for this turn."""
    return cast(RunnableConfig, {
        "configurable": {"thread_id": session_id, "checkpoint_ns": ""},
        "metadata": {"turn_id": turn_id, "branch_id": branch_id},
        "tags": ["workflowweave", "agent"],
    })


async def cancel_tools(context: AgentContext) -> None:
    """Cancel and await the whole tool task tree before releasing the turn."""
    tasks = list(context.scope.tasks.values())
    for task in tasks:
        if not task.done() and not task.cancelling():
            task.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            raise result


@asynccontextmanager
async def tool_scope(context: AgentContext):
    """Own all tool tasks started by a graph turn and always await cleanup."""
    try:
        yield context.scope
    finally:
        await cancel_tools(context)


async def stream_graph(graph: Any, messages: list[Any], *, context: AgentContext,
                       config: RunnableConfig, log: Any, idle_timeout: float,
                       publication: list[bool] | None = None) -> tuple[dict[str, Any], bool]:
    """Consume one v2 event stream, retaining provider deltas exactly once."""
    stream = graph.astream_events(
        {"messages": messages, "turn_id": context.turn_id, "branch_id": context.branch_id},
        config,
        version="v2",
        context=context,
    )
    final_state: dict[str, Any] | None = None
    published = False
    awaiting_model = False
    try:
        while True:
            try:
                if awaiting_model:
                    event = await asyncio.wait_for(stream.__anext__(), timeout=idle_timeout)
                else:
                    event = await stream.__anext__()
            except StopAsyncIteration:
                break
            except TimeoutError as exc:
                raise WorkFLowWeaveError(
                    "model_idle_timeout", "模型流式输出在无活动超时内没有新事件",
                    {"idle_timeout": idle_timeout},
                ) from exc

            event_name = event.get("event") if isinstance(event, dict) else None
            if event_name == "on_chat_model_start":
                awaiting_model = True
            is_summary = event.get("metadata", {}).get("lc_source") == "summarization"
            if event_name == "on_chat_model_stream" and not is_summary:
                data = event.get("data", {})
                delta = message_delta(data.get("chunk")) if isinstance(data, dict) else None
                if delta is not None:
                    published = True
                    if publication is not None:
                        publication[0] = True
                    await log.append(
                        "message.delta", turn_id=context.turn_id,
                        message_id=getattr(data.get("chunk"), "id", None), **delta,
                    )
            if event_name == "on_chat_model_end":
                awaiting_model = False
            if event_name == "on_chain_end" and isinstance(event.get("data"), dict):
                output = event["data"].get("output")
                if isinstance(output, dict) and isinstance(output.get("messages"), list):
                    final_state = output
    except BaseException as exc:
        try:
            exc._agent_published = published
        except Exception:
            pass
        raise
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()
    if final_state is None:
        raise WorkFLowWeaveError("invalid_response", "Agent 图没有返回最终消息状态")
    return final_state, published

def message_delta(chunk: Any) -> dict[str, Any] | None:
    content = getattr(chunk, "content", None)
    tool_calls = getattr(chunk, "tool_call_chunks", None) or getattr(chunk, "tool_calls", None)
    delta: dict[str, Any] = {}
    if isinstance(content, str) and content:
        delta["content"] = content
    elif isinstance(content, list) and content:
        delta["content"] = content
    if tool_calls:
        delta["tool_calls"] = tool_calls
    kwargs = getattr(chunk, "additional_kwargs", {}) or {}
    reasoning = kwargs.get("reasoning_content") or kwargs.get("reasoning")
    if not reasoning:
        reasoning = getattr(chunk, "reasoning_content", None)
    if not reasoning and isinstance(content, list):
        reasoning = "".join(
            block.get("reasoning", "") if block.get("type") == "reasoning"
            else block.get("thinking", "")
            for block in content if isinstance(block, dict)
            and (block.get("type") == "reasoning" and isinstance(block.get("reasoning"), str)
                 or block.get("type") == "thinking" and isinstance(block.get("thinking"), str))
        )
    if isinstance(reasoning, str) and reasoning:
        delta["reasoning"] = reasoning
    return delta or None


def final_reasoning(result: dict[str, Any]) -> str:
    for message in reversed(result.get("messages", [])):
        if isinstance(message, AIMessage):
            return (message_delta(message) or {}).get("reasoning", "")
    return ""
