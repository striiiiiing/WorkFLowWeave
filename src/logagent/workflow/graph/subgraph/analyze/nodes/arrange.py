from langgraph.runtime import Runtime

from logagent.workflow.execution.context import WorkflowContext
from logagent.workflow.graph.subgraph.nodes.state import phase


def arrange(state, runtime: Runtime[WorkflowContext]):
    snapshot = runtime.context.snapshot
    wf = snapshot.workflow
    items = state["analysis_items"]
    failed = sum(i["status"] != "success" for i in items.values())
    stopped = failed == len(items) or bool(
        failed and (wf.analysis_failure == "stop" or not wf.send_partial)
    )
    error = {"code": "analysis_stopped", "message": "分析失败策略阻止下游阶段"} if stopped else None
    keep_input = wf.fan_in and "$input" in wf.fan_in.ordered_inputs(wf.analyses)
    return phase(
        state,
        "analyze",
        stopped=stopped,
        status="failed" if stopped else "running",
        error=error,
        degraded=state.get("degraded", False) or bool(failed),
        shared_input=state["shared_input"] if keep_input else "",
    )
