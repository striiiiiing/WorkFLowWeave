"""父图入口选择与恢复材料核验；执行位置仅由 LangGraph 提供。"""

from __future__ import annotations

import asyncio

from logagent.errors import LogAgentError
from logagent.models import CollectionContext, WorkflowSnapshot
from logagent.workflow.graph import GRAPH_REVISION
from logagent.workflow.nodes import ArchiveRuntime

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


async def prepare_recovery(service, session_id, *, stage=None, checkpoint_id=None):
    if stage is not None and stage not in STAGES:
        raise LogAgentError("invalid_argument", "阶段必须是 collect、analyze、aggregate 或 notify")
    if stage is None and checkpoint_id is not None:
        raise LogAgentError("invalid_argument", "中断续跑不能指定历史 checkpoint")
    config = {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}}
    current = await service._checkpointer.aget_tuple(config)
    if current is None:
        raise LogAgentError("checkpoint_missing", "缺少原 checkpoint，无法从业务存档猜测进度")
    compatible(current.checkpoint.get("channel_values", {}))
    entry = await asyncio.to_thread(service.session_store.entry, session_id, "snapshot")
    if entry is None or entry["availability"] != "available" or entry["body"] is None:
        raise LogAgentError("recovery_unavailable", "原配置快照不可用")
    snapshot = WorkflowSnapshot.model_validate(entry["body"]["snapshot"])
    saved_path = entry["body"].get("log_path")
    runtime = ArchiveRuntime(service.session_store, session_id, snapshot.workflow.backup)
    context = CollectionContext(
        snapshot.workflow.id, session_id, saved_path, service.credentials, service.session_view,
    )
    graph = service._graph(runtime, snapshot, context)
    latest = await graph.aget_state(config, subgraphs=True)
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
            raise LogAgentError("stage_unavailable", "所选轮次没有匹配的父图阶段入口",
                                {"stage": stage, "checkpoint_id": checkpoint_id})
    await _check_inputs(service, runtime, snapshot, selected, stage)
    return snapshot, saved_path, graph, selected


async def _check_inputs(service, runtime, snapshot, selected, stage):
    """只要求本次执行会读取的上游或未完成分支正文，不检查废弃下游历史。"""
    phases = selected.values.get("phases", {})
    target = stage
    if target is None:
        target = selected.next[0] if selected.next else "finish"
    required = {
        "collect": (), "analyze": ("collect",), "aggregate": ("analyze",),
        "notify": ("aggregate",), "finish": ("aggregate",) if phases.get("aggregate") else (),
    }.get(target, ())
    if target == "aggregate" and snapshot.workflow.fan_in and "$input" in snapshot.workflow.fan_in.ordered_inputs(snapshot.workflow.analyses):
        required = ("collect", "analyze")
    for name in required:
        key = phases.get(name)
        if not key:
            raise LogAgentError("recovery_unavailable", "恢复入口缺少上游结果引用", {"stage": name})
        await runtime.read(key)
    if stage is not None:
        return
    if target in {"collect", "analyze"}:
        _, entries = await asyncio.to_thread(service.session_store.entries, runtime.session_id)
        for entry in entries:
            if (entry["scope"] == target
                    and entry["summary"].get("execution_epoch") == selected.values["execution_epoch"]):
                await runtime.read(entry["write_key"])
    # Pending branch writes can be newer than the child checkpoint. Inspect the
    # latest tuple of each active invocation, never historical/discarded rounds.
    async def check_task(task):
        child = getattr(task, "state", None)
        if child is None:
            return
        child_config = child.config if hasattr(child, "config") else child
        if not isinstance(child_config, dict):
            return
        saved = await service._checkpointer.aget_tuple(child_config)
        if saved:
            values = saved.checkpoint.get("channel_values", {})
            refs = list(values.get("items", {}).values())
            for _, channel, value in saved.pending_writes or ():
                if channel == "items" and isinstance(value, dict):
                    refs.extend(value.values())
            for ref in set(refs):
                if ref:
                    await runtime.read(ref)
        for nested in getattr(child, "tasks", ()):
            await check_task(nested)
    for task in selected.tasks:
        await check_task(task)
