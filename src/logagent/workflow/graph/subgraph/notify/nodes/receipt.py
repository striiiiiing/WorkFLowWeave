import asyncio

from langgraph.runtime import Runtime

from logagent.models import DeliveryResult, Notification, copy_model
from logagent.workflow.execution.context import WorkflowContext
from logagent.workflow.graph.subgraph.notify.nodes.uncertain import uncertain


async def receipt(state, runtime: Runtime[WorkflowContext]):
    snapshot = runtime.context.snapshot
    output_id, channel_id = state["output_id"], state["channel_id"]
    key = f"{output_id}:{channel_id}"
    config = snapshot.channels[channel_id]
    if not config.enabled:
        result = DeliveryResult(
            channel_id=channel_id, output_id=output_id, status="skipped", attempts=0
        )
    elif (state["execution_epoch"], key) not in runtime.context.fresh_intents:
        result = uncertain(channel_id, output_id)
    else:
        note = Notification(
            session_id=state["session_id"],
            output_id=output_id,
            title=snapshot.workflow.name or snapshot.workflow.id,
            text=state["text"],
        )
        raw = await runtime.context.channel_manager.send(copy_model(config), note)
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError
        result = DeliveryResult.model_validate(
            raw.model_dump(mode="json") if isinstance(raw, DeliveryResult) else raw
        )
        if result.channel_id != channel_id or result.output_id != output_id:
            raise ValueError("Delivery identity mismatch")
    return {"deliveries": {key: result.model_dump(mode="json")}}
