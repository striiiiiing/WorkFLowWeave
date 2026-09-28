"""采集与分析 fan-out/fan-in 子图。"""

from __future__ import annotations

import asyncio

from langgraph.graph import END, START, StateGraph

from logagent.errors import exception_error
from logagent.models import CollectionResult, ErrorInfo, copy_model
from logagent.workflow.nodes import archive_node, epoch_key
from logagent.workflow.stream import tagged_node


def build_work_subgraph(*, stage, runtime, snapshot, context, stage_nodes, state_schema,
                        collector_manager, safe_node, registry):
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
                attempt_key = state["archive_key"].replace("collect:item:", "acquisition:item:", 1)
                attempt = await asyncio.to_thread(runtime.store.entry, runtime.session_id, attempt_key)
                if attempt is not None:
                    return CollectionResult(
                        source_id=ident, status="unknown",
                        error=ErrorInfo(code="collection_outcome_unknown",
                                        message="来源调用已开始但结果未知，不自动重放"),
                        metadata={"result_known": False, "phase": "dispatched"},
                    ).model_dump(mode="json")
                await runtime.save(attempt_key, stage="collect", scope="acquisition",
                                   summary={"item_id": ident, "result_known": False},
                                   body={"dispatched": True})
                try:
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
                incoming = await stage_nodes.result(state, required=("collect",))
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
            summarize=lambda body, ident=ident: {
                "item_id": ident, "item_status": body["status"],
                "error": body.get("error"),
            },
            publish=lambda key, summary, ident=ident: {"items": {ident: key}},
        )

        async def bounded(state, archived=archived, ident=ident):
            """取得并发许可后选择本项幂等键，执行或复用存档节点。"""
            async with semaphore:
                if stage == "collect" and state.get("reuse_collection_epoch"):
                    key = f"collect:item:{ident}:epoch:{state['reuse_collection_epoch']}"
                    await runtime.read(key)
                    return {"items": {ident: key}}
                key = epoch_key(state, f"{stage}:item:{ident}")
                return await archived({**state, "archive_key": key})

        graph.add_node(
            f"work_{ident}",
            tagged_node(registry, (stage, f"work_{ident}"), safe_node(bounded),
                        f"workflow:{stage}:item"),
        )
        graph.add_edge(START, f"work_{ident}")
        graph.add_edge(f"work_{ident}", "arrange")
    graph.add_node("arrange", (stage_nodes.collection_result_node() if stage == "collect"
                               else stage_nodes.analysis_result_node()))
    graph.add_edge("arrange", END)
    return graph.compile(checkpointer=None)
