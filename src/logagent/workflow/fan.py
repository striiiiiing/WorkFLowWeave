"""采集与分析 fan-out/fan-in 子图。"""

from __future__ import annotations

import asyncio

from langgraph.graph import END, START, StateGraph

from logagent.errors import exception_error
from logagent.models import CollectionResult, ErrorInfo, copy_model
from logagent.workflow.nodes import archive_node


def build_work_subgraph(*, stage, runtime, snapshot, context, stage_nodes, state_schema,
                        collector_manager, safe_node):
    """为每个来源或分析任务建立独立分支，汇合后按定义顺序整理。

    semaphore 同时覆盖外部调用和本项存档，保证并发限制也约束提交边界。
    """
    wf = snapshot.workflow
    graph = StateGraph(state_schema)
    keys = wf.sources if stage == "collect" else [task.id for task in wf.analyses]
    concurrency = wf.collection_concurrency if stage == "collect" else wf.analysis_concurrency
    semaphore = asyncio.Semaphore(concurrency)
    for ident in keys:

        async def operation(state, ident=ident):
            """执行单个采集或分析任务，并返回可存档结果。

            采集异常和超时保留为对应状态；分析分支读取同一份完整共享输入。
            """
            if stage == "collect":
                config = snapshot.sources[ident]
                try:
                    async with asyncio.timeout(config.timeout):
                        raw = await collector_manager.collect(copy_model(config), context)
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                    result = CollectionResult.model_validate(
                        raw.model_dump(mode="json")
                        if isinstance(raw, CollectionResult)
                        else raw
                    )
                    if result.source_id != ident:
                        raise ValueError("Collector identity mismatch")
                except TimeoutError:
                    result = CollectionResult(
                        source_id=ident,
                        status="timeout",
                        error=ErrorInfo(code="collection_timeout", message="来源采集超时"),
                    )
                except Exception as exc:
                    result = CollectionResult(
                        source_id=ident,
                        status="failed",
                        error=exception_error(
                            exc, code="collection_failed", message="来源采集失败"
                        ),
                    )
            else:
                incoming = await stage_nodes._result(state, required=("collect",))
                task = next(task for task in wf.analyses if task.id == ident)
                result = await stage_nodes._analysis_call(
                    snapshot.ai[task.ai], task, incoming.shared_input, ident, incoming, task.model
                )
            return result.model_dump(mode="json")

        archived = archive_node(
            runtime,
            scope=stage,
            stage=stage,
            key=lambda state: state["archive_key"],
            operation=operation,
            category="collection" if stage == "collect" else "analysis",
            summarize=lambda body: {"item_status": body["status"]},
            publish=lambda key, summary, ident=ident: {"items": {ident: key}},
        )

        async def bounded(state, archived=archived, ident=ident):
            """取得并发许可后选择本项幂等键，执行或复用存档节点。"""
            async with semaphore:
                key = await asyncio.to_thread(item_key, runtime, stage, ident, state)
                return await archived({**state, "archive_key": key})

        graph.add_node(f"work_{ident}", safe_node(bounded))
        graph.add_edge(START, f"work_{ident}")
        graph.add_edge(f"work_{ident}", "arrange")
    graph.add_node("arrange", stage_nodes._phase_node(stage, runtime, snapshot))
    graph.add_edge("arrange", END)
    return graph.compile()

def item_key(runtime, stage, ident, state):
    """选择条目存档键；重试时复用成功项。"""
    base = f"{stage}:item:{ident}"
    generation = state.get("generation", 0)
    if not generation:
        return base
    _, entries = runtime.store.entries(runtime.session_id)
    successful = next((
        entry for entry in entries
        if entry["scope"] == stage
        and (entry["write_key"] == base or entry["write_key"].startswith(base + ":attempt:"))
        and entry["summary"].get("item_status") == "success"
    ), None)
    return successful["write_key"] if successful else f"{base}:attempt:{generation}"
