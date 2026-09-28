"""并行投递以 checkpoint intent 屏障准入；归档不决定发送资格。"""
from __future__ import annotations

import asyncio

from langgraph.graph import END, START, StateGraph

from logagent.models import DeliveryResult, Notification, copy_model
from logagent.workflow.stream import tagged_node


def build_notification_graph(*, snapshot, state_schema, arrange, channel_manager, uncertain, registry):
    graph = StateGraph(state_schema)
    wf = snapshot.workflow
    output_ids = ["final"] if wf.fan_in else [task.id for task in wf.analyses]
    fresh = set()
    receipts = []
    for oi, oid in enumerate(output_ids):
        for ci, cid in enumerate(wf.channels):
            key = f"{oid}:{cid}"
            async def intent(state, oid=oid, cid=cid, key=key):
                if oid not in state["outputs"]:
                    return {}
                fresh.add((state["execution_epoch"], key))
                return {"intents": {key: {"output_id": oid, "channel_id": cid}}}
            async def receipt(state, oid=oid, cid=cid, key=key):
                if oid not in state["outputs"]:
                    return {}
                config = snapshot.channels[cid]
                if not config.enabled:
                    result = DeliveryResult(channel_id=cid, output_id=oid, status="skipped", attempts=0)
                elif (state["execution_epoch"], key) not in fresh:
                    result = uncertain(cid, oid)
                else:
                    note = Notification(session_id=state["session_id"], output_id=oid,
                                        title=wf.name or wf.id, text=state["outputs"][oid])
                    try:
                        async with asyncio.timeout(config.timeout):
                            raw = await channel_manager.send(copy_model(config), note)
                        if asyncio.current_task().cancelling():
                            raise asyncio.CancelledError
                        result = DeliveryResult.model_validate(raw.model_dump(mode="json") if isinstance(raw, DeliveryResult) else raw)
                        if result.channel_id != cid or result.output_id != oid:
                            raise ValueError("Delivery identity mismatch")
                    except TimeoutError:
                        result = uncertain(cid, oid)
                        result.status = "timeout"
                    except Exception:
                        result = uncertain(cid, oid)
                return {"deliveries": {key: result.model_dump(mode="json")}}
            i, r = f"intent_{oi}_{ci}", f"receipt_{oi}_{ci}"
            graph.add_node(i, intent)
            graph.add_node(r, tagged_node(registry, ("notify", r), receipt, "workflow:delivery"))
            graph.add_edge(START, i)
            graph.add_edge(i, r)
            receipts.append(r)
    graph.add_node("arrange", arrange)
    graph.add_edge(receipts if receipts else START, "arrange")
    graph.add_edge("arrange", END)
    return graph.compile(checkpointer=None)
