from langgraph.runtime import Runtime

from logagent.errors import LogAgentError
from logagent.models import CollectionResult, InputView
from logagent.workflow.execution.context import WorkflowContext
from logagent.workflow.graph.subgraph.nodes.state import phase
from logagent.workflow.input_processing import process_input


def arrange(state, runtime: Runtime[WorkflowContext]):
    snapshot = runtime.context.snapshot
    wf = snapshot.workflow
    items = [CollectionResult.model_validate(state["collection_items"][key]) for key in wf.sources]
    processing_error = None
    try:
        text, views = process_input(snapshot, items, runtime.context.input_token_counters())
    except LogAgentError as exc:
        processing_error = exc.info
        text = ""
        views = [InputView(source_id=source_id, status="failed", error=processing_error)
                 for source_id in wf.sources]
    valid = [view.text for view in views if view.status == "success" and view.text]
    error = None
    for item in items:
        if item.status == "success":
            continue
        source = snapshot.sources[item.source_id]
        if source.call is not None and source.call.kind == "mcp":
            policy = source.on_error
        else:
            policy_name = "error" if item.status in {"failed", "timeout"} else item.status
            policy = getattr(source, "on_" + policy_name)
        if policy == "stop":
            error = {"code": "collection_stopped", "message": "来源策略要求停止下游阶段"}
            break
    if not error:
        for view in views:
            if view.status == "failed" and snapshot.sources[view.source_id].on_error == "stop":
                error = {"code": "input_processing_stopped", "message": "来源输入处理失败，策略要求停止下游阶段"}
                break
    if not valid and wf.on_all_empty == "stop" and not error:
        error = {"code": "all_empty", "message": "所有来源均无有效内容"}
    if processing_error and not error:
        error = processing_error.model_dump(mode="json")
    return phase(
        state,
        "collect",
        shared_input=text,
        input_views=[view.model_dump(mode="json") for view in views],
        stopped=bool(error) or not valid,
        status="failed" if error else "running",
        error=error,
        degraded=any(i.status in {"failed", "missing", "timeout"} for i in items),
    )
