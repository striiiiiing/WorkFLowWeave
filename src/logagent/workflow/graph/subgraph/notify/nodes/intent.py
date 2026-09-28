from langgraph.runtime import Runtime

from logagent.workflow.execution.context import WorkflowContext


def intent(state, runtime: Runtime[WorkflowContext]):
    output_id, channel_id = state["output_id"], state["channel_id"]
    key = f"{output_id}:{channel_id}"
    runtime.context.fresh_intents.add((state["execution_epoch"], key))
    return {"intents": {key: {"output_id": output_id, "channel_id": channel_id}}}
