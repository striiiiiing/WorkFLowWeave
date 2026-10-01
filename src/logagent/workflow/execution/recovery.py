"""父图入口选择与恢复材料核验；执行位置仅由 LangGraph 提供。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from logagent.errors import LogAgentError
from logagent.models import WorkflowSnapshot
from logagent.workflow.graph.workflow import GRAPH_REVISION

STAGES = ("collect", "analyze", "aggregate", "notify")


def compatible(values):
    if values.get("graph_revision") != GRAPH_REVISION:
        raise LogAgentError(
            "checkpoint_incompatible",
            "checkpoint 图版本不匹配，无法继续执行",
            {"expected": GRAPH_REVISION, "actual": values.get("graph_revision")},
        )


async def find_request(saver, session_id, request_id):
    config = {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}}
    async for saved in saver.alist(config):
        values = saved.checkpoint.get("channel_values", {})
        if values.get("resume_request_id") == request_id:
            return values
    return None


async def prepare_recovery(
    session_id, *, saver, store, view, graph, stage=None, checkpoint_id=None
):
    if stage is not None and stage not in STAGES:
        raise LogAgentError("invalid_argument", "阶段必须是 collect、analyze、aggregate 或 notify")
    if stage is None and checkpoint_id is not None:
        raise LogAgentError("invalid_argument", "中断续跑不能指定历史 checkpoint")
    config = {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}}
    current = await saver.aget_tuple(config)
    if current is None:
        record = await view.get_session(session_id)
        deadline = await asyncio.to_thread(
            store.checkpoint_deadline, session_id, record.execution_epoch
        )
        if deadline is not None and deadline <= datetime.now(UTC):
            raise LogAgentError(
                "checkpoint_expired",
                "执行恢复保留期已到期",
                {"checkpoint_expires_at": deadline.isoformat()},
            )
        raise LogAgentError("checkpoint_missing", "缺少原 checkpoint，无法从业务存档猜测进度")
    compatible(current.checkpoint.get("channel_values", {}))
    values = current.checkpoint["channel_values"]
    snapshot = WorkflowSnapshot.model_validate(values["snapshot"])
    saved_path = values.get("log_path")
    latest = await graph.aget_state(config)
    selected = latest
    if stage is not None:
        selected = None
        epoch = latest.values["execution_epoch"]
        async for candidate in graph.aget_state_history(config):
            cid = candidate.config["configurable"]["checkpoint_id"]
            if checkpoint_id is not None and cid != checkpoint_id:
                continue
            if checkpoint_id is None and candidate.values.get("execution_epoch") != epoch:
                continue
            if candidate.next == (stage,):
                compatible(candidate.values)
                selected = candidate
                break
            if checkpoint_id is not None:
                break
        if selected is None:
            raise LogAgentError(
                "stage_unavailable",
                "所选轮次没有匹配的父图阶段入口",
                {"stage": stage, "checkpoint_id": checkpoint_id},
            )
    deadline = await asyncio.to_thread(
        store.checkpoint_deadline, session_id, selected.values["execution_epoch"]
    )
    if deadline is not None and deadline <= datetime.now(UTC):
        raise LogAgentError(
            "checkpoint_expired",
            "执行恢复保留期已到期",
            {"checkpoint_expires_at": deadline.isoformat()},
        )
    return snapshot, saved_path, graph, selected
