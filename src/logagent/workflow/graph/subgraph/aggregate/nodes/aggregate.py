from types import SimpleNamespace

from langgraph.runtime import Runtime

from logagent.workflow.execution.context import WorkflowContext
from logagent.workflow.graph.subgraph.nodes.analysis import analyze_call
from logagent.workflow.graph.subgraph.nodes.state import phase


async def aggregate(state, runtime: Runtime[WorkflowContext]):
    snapshot = runtime.context.snapshot
    wf = snapshot.workflow
    items = state["analysis_items"]
    outputs, error, model_result = {}, None, None
    if wf.fan_in is None:
        outputs = {
            t.id: items[t.id]["text"] for t in wf.analyses if items[t.id]["status"] == "success"
        }
    else:
        parts = []
        for key in wf.fan_in.ordered_inputs(wf.analyses):
            if key == "$input":
                parts.append(state["shared_input"])
            elif items[key]["status"] == "success":
                parts.append(items[key]["text"])
            elif wf.fan_in.mark_incomplete:
                parts.append(f"[{key}: incomplete]")
        text = wf.fan_in.separator.join(parts)
        reused = wf.fan_in.reused_task(wf.analyses)
        ai_id = reused.ai if reused else wf.fan_in.ai
        model = reused.model if reused else wf.fan_in.model
        if not text.strip():
            error = {"code": "aggregate_empty", "message": "汇总未产生有效正文"}
        elif ai_id:
            context = SimpleNamespace(
                workflow_id=wf.id, session_id=state["session_id"], stage="aggregate"
            )
            result = await analyze_call(
                snapshot,
                runtime.context.ai_service,
                snapshot.ai[ai_id],
                wf.fan_in,
                text,
                "final",
                context,
                model,
            )
            model_result = result.model_dump(mode="json", exclude={"text"})
            if result.status != "success":
                error = {"code": "aggregate_failed", "message": "AI 汇总失败"}
            else:
                text = result.text
        if not error:
            outputs = {"final": text}
    return phase(
        state,
        "aggregate",
        outputs=outputs,
        aggregate_meta=model_result,
        analysis_items={},
        shared_input="",
        stopped=bool(error),
        error=error,
        status="failed" if error else "running",
    )
