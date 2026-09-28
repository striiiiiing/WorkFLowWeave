"""采集业务结果由采集服务管理预算，再按来源策略汇合。"""

from langgraph.runtime import Runtime

from logagent.models import CollectionResult, copy_model
from logagent.workflow.execution.context import WorkflowContext


async def collect(state, runtime: Runtime[WorkflowContext]):
    dependencies = runtime.context
    source = dependencies.snapshot.sources[state["source_id"]]
    async with dependencies.collection_slots:
        raw = await dependencies.collector_manager.collect(
            copy_model(source), dependencies.collection
        )
    result = CollectionResult.model_validate(
        raw.model_dump(mode="json") if isinstance(raw, CollectionResult) else raw
    )
    if result.source_id != source.id:
        raise ValueError("Collector identity mismatch")
    return {"collection_items": {source.id: result.model_dump(mode="json")}}
