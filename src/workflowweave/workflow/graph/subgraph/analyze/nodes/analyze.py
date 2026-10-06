from types import SimpleNamespace

from langgraph.runtime import Runtime

from workflowweave.workflow.execution.context import WorkflowContext
from workflowweave.workflow.graph.subgraph.nodes.analysis import analyze_call


async def analyze(state, runtime: Runtime[WorkflowContext]):
    snapshot = runtime.context.snapshot
    task = next(task for task in snapshot.workflow.analyses if task.id == state["analysis_id"])
    context = SimpleNamespace(
        workflow_id=snapshot.workflow.id, session_id=state["session_id"], stage="analyze"
    )
    async with runtime.context.analysis_slots:
        result = await analyze_call(
            snapshot,
            runtime.context.ai_service,
            snapshot.ai[task.ai],
            task,
            state["analysis_input"],
            task.id,
            context,
            task.model,
            agent_service=runtime.context.agent_service,
            execution_epoch=state["execution_epoch"],
        )
    return {"analysis_items": {task.id: result.model_dump(mode="json")}}
