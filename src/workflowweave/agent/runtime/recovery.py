"""Reconcile LangGraph checkpoints with durable Agent event facts."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.graph import END

from workflowweave.errors import WorkFLowWeaveError


async def ensure_checkpoint_present(checkpointer: Any, session_id: str, *,
                                    require_existing: bool) -> None:
    """Fail before model acquisition when a historical thread has no state."""
    if not require_existing or checkpointer is None:
        return
    getter = getattr(checkpointer, "aget_tuple", None)
    if getter is None:
        return
    try:
        checkpoint = await getter({"configurable": {"thread_id": session_id}})
    except Exception as exc:
        raise WorkFLowWeaveError(
            "checkpoint_corrupt", "Agent checkpoint 无法读取，不能继续会话",
            {"exception_type": type(exc).__name__},
        ) from exc
    if checkpoint is None:
        raise WorkFLowWeaveError(
            "checkpoint_missing", "Agent checkpoint 缺失，不能猜测历史继续",
            {"session_id": session_id},
        )


async def prepare_checkpoint(graph: Any, projection_graph: Callable[[], Any], session_id: str,
                             event_log: Any, turn_id: str, *, require_existing: bool) -> None:
    """Close interrupted tool boundaries without inferring unknown outcomes.

    JSONL identifies side effects that completed or have unknown outcomes. The
    checkpoint supplies the pending graph boundary. If either side is
    unavailable, recovery fails explicitly instead of rebuilding plausible
    state and risking a duplicate side effect.
    """
    config = {"configurable": {"thread_id": session_id}}
    try:
        state = await graph.aget_state(config)
    except Exception as exc:
        raise WorkFLowWeaveError(
            "checkpoint_corrupt", "Agent checkpoint 无法读取，不能继续会话",
            {"exception_type": type(exc).__name__},
        ) from exc

    if state is None:
        if require_existing:
            raise WorkFLowWeaveError(
                "checkpoint_missing", "Agent checkpoint 缺失，不能猜测历史继续",
                {"session_id": session_id},
            )
        return

    values = getattr(state, "values", None) or {}
    messages = values.get("messages", []) if isinstance(values, dict) else []
    next_nodes = tuple(getattr(state, "next", ()) or ())
    checkpoint_id = (getattr(state, "config", None) or {}).get("configurable", {}).get("checkpoint_id")
    if require_existing and not messages and not next_nodes and not checkpoint_id:
        raise WorkFLowWeaveError(
            "checkpoint_missing", "Agent checkpoint 缺失，不能猜测历史继续",
            {"session_id": session_id},
        )
    if not next_nodes:
        return

    pending: list[str] = []
    replied: set[str] = set()
    for message in messages:
        tool_call_id = getattr(message, "tool_call_id", None)
        if isinstance(tool_call_id, str):
            replied.add(tool_call_id)
    for message in messages:
        for call in getattr(message, "tool_calls", ()) or ():
            call_id = call.get("id") if isinstance(call, dict) else None
            if isinstance(call_id, str) and call_id not in replied:
                pending.append(call_id)

    if not pending:
        terminal = next((event for event in reversed(event_log.events)
                         if event["type"] in {
                             "turn.completed", "turn.failed", "turn.cancelled", "turn.interrupted",
                         }), None)
        if (terminal is not None and terminal["type"] != "turn.completed"
                and set(next_nodes) <= set(getattr(graph, "nodes", {}))):
            await projection_graph().aupdate_state(
                config, {"messages": messages}, as_node="projection",
            )
            await event_log.append(
                "checkpoint.repaired", turn_id=turn_id,
                result="continuation_boundary", previous_terminal=terminal["type"],
            )
            return
        raise WorkFLowWeaveError(
            "checkpoint_corrupt", "Agent checkpoint 存在未完成节点但没有可修复工具调用",
            {"next": list(next_nodes)},
        )
    if "tools" not in next_nodes:
        raise WorkFLowWeaveError(
            "checkpoint_corrupt", "Agent checkpoint 的未完成节点不是工具边界",
            {"next": list(next_nodes)},
        )

    repairs = [ToolMessage(
        content=json.dumps({"status": "outcome_unknown", "reason": "interrupted"},
                           ensure_ascii=False, sort_keys=True),
        tool_call_id=call_id,
    ) for call_id in pending]
    try:
        await graph.aupdate_state(config, {"messages": repairs}, as_node="tools")
        await graph.aupdate_state(config, None, as_node=END)
    except Exception as exc:
        raise WorkFLowWeaveError(
            "checkpoint_corrupt", "Agent checkpoint 无法写入中断工具结果",
            {"exception_type": type(exc).__name__},
        ) from exc
    await event_log.append(
        "checkpoint.repaired", turn_id=turn_id,
        tool_call_ids=pending, result="outcome_unknown",
    )
