from langgraph.runtime import Runtime

from logagent.workflow.execution.context import WorkflowContext
from logagent.workflow.graph.subgraph.nodes.state import phase
from logagent.workflow.storage.collection import collection_input


def arrange(state, runtime: Runtime[WorkflowContext]):
    snapshot = runtime.context.snapshot
    wf = snapshot.workflow
    items = [state["collection_items"][key] for key in wf.sources]
    valid = [item["text"] for item in items if item["status"] == "success"]
    text = collection_input(wf, items)
    error = None
    for item in items:
        if item["status"] == "success":
            continue
        policy = "error" if item["status"] in {"failed", "timeout"} else item["status"]
        if getattr(snapshot.sources[item["source_id"]], "on_" + policy) == "stop":
            error = {"code": "collection_stopped", "message": "来源策略要求停止下游阶段"}
            break
    if not valid and wf.on_all_empty == "stop" and not error:
        error = {"code": "all_empty", "message": "所有来源均无有效内容"}
    return phase(
        state,
        "collect",
        shared_input=text,
        stopped=bool(error) or not valid,
        status="failed" if error else "running",
        error=error,
        degraded=any(i["status"] in {"failed", "missing", "timeout"} for i in items),
    )
