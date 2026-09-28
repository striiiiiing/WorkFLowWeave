"""所有业务节点结束后交接归档，再统一清理子图执行副本。"""

from langgraph.runtime import Runtime

from logagent.workflow.execution.context import WorkflowContext


async def cleanup(state, runtime: Runtime[WorkflowContext]):
    await runtime.context.finalize(state["session_id"])
    return {}
