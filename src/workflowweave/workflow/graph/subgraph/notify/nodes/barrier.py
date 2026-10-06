"""等待 intent 事实经唯一事件消费者提交后再执行 receipt。"""

from langgraph.runtime import Runtime

from workflowweave.workflow.execution.context import WorkflowContext


async def wait_intent(state, runtime: Runtime[WorkflowContext]):
    key = f"{state['output_id']}:{state['channel_id']}"
    await runtime.context.wait_for_intent(state["execution_epoch"], key)
    return {}
