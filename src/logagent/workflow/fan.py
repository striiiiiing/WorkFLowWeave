"""采集/分析的逐项 LangGraph 任务，返回内容而不访问归档。"""
from __future__ import annotations

import asyncio

from langgraph.graph import END, START, StateGraph

from logagent.errors import exception_error
from logagent.models import CollectionResult, ErrorInfo, copy_model
from logagent.workflow.stream import tagged_node


def build_work_subgraph(*, stage, snapshot, context, operations, state_schema, collector_manager, registry):
    wf = snapshot.workflow
    graph = StateGraph(state_schema)
    keys = wf.sources if stage == "collect" else [task.id for task in wf.analyses]
    semaphore = asyncio.Semaphore(wf.collection_concurrency if stage == "collect" else wf.analysis_concurrency)
    channel = "collection_items" if stage == "collect" else "analysis_items"
    for ident in keys:
        async def work(state, ident=ident):
            async with semaphore:
                if stage == "analyze":
                    task = next(task for task in wf.analyses if task.id == ident)
                    result = await operations.analyze_item(state, task)
                else:
                    config = snapshot.sources[ident]
                    try:
                        async with asyncio.timeout(config.timeout):
                            raw = await collector_manager.collect(copy_model(config), context)
                        if asyncio.current_task().cancelling():
                            raise asyncio.CancelledError
                        result = CollectionResult.model_validate(raw.model_dump(mode="json") if isinstance(raw, CollectionResult) else raw)
                        if result.source_id != ident:
                            raise ValueError("Collector identity mismatch")
                    except TimeoutError:
                        result = CollectionResult(source_id=ident, status="timeout",
                            error=ErrorInfo(code="collection_timeout", message="来源采集超时"))
                    except Exception as exc:
                        result = CollectionResult(source_id=ident, status="failed",
                            error=exception_error(exc, code="collection_failed", message="来源采集失败"))
                return {channel: {ident: result.model_dump(mode="json")}}
        name = f"work_{ident}"
        graph.add_node(name, tagged_node(registry, (stage, name), work, f"workflow:{stage}:item"))
        graph.add_edge(START, name)
        graph.add_edge(name, "arrange")
    graph.add_node("arrange", operations.collection if stage == "collect" else operations.analysis)
    graph.add_edge("arrange", END)
    return graph.compile(checkpointer=None)
