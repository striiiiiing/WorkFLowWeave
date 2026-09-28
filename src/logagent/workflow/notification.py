"""通知阶段 LangGraph 节点。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from logagent.models import DeliveryResult, copy_model
from logagent.workflow.nodes import ArchiveRuntime, archive_node, epoch_key
from logagent.workflow.stream import tagged_node


def build_notification_graph(*, runtime: ArchiveRuntime, snapshot, state_schema,
                             result_reader: Callable, arrange: Callable,
                             channel_manager, safe_node: Callable, uncertain: Callable, registry):
    """构造通知子图：每个输出/渠道都有独立的 intent 和 receipt 节点。

    ``intent -> receipt`` 是显式边。intent 事务提交后才允许 receipt 节点调用
    外部 Channel；旧 intent 没有可靠 receipt 时由节点生成 uncertain，不补发。
    """
    graph = StateGraph(state_schema)
    wf = snapshot.workflow
    output_ids = ["final"] if wf.fan_in else [task.id for task in wf.analyses]
    fresh_intents = set()
    receipts = []
    for output_index, output_id in enumerate(output_ids):
        for channel_index, cid in enumerate(wf.channels):
            intent_key = f"intent:{output_id}:{cid}"
            receipt_key = f"delivery:{output_id}:{cid}"

            async def intention(state, oid=output_id, cid=cid, key=intent_key):
                """记录本次新建意图身份，返回不含通知正文的管理事实。"""
                fresh_intents.add(epoch_key(state, key))
                return {"output_id": oid, "channel_id": cid}

            intent_archive = archive_node(
                runtime,
                scope="notification",
                stage="notify",
                key=lambda state, key=intent_key: epoch_key(state, key),
                category=None,
                operation=intention,
                publish=lambda key, summary: {},
            )

            async def intent_node(state, oid=output_id, archived=intent_archive):
                """仅为冻结输出中实际存在的输出建立或复用发送意图。"""
                result = await result_reader(state, required=("aggregate",))
                if oid not in result.outputs:
                    return {}
                return await archived(state)

            async def delivery(state, oid=output_id, cid=cid, ikey=intent_key):
                """对本次新意图发送原冻结通知，并返回待存档回执。

                禁用渠道记 skipped；旧意图、发送异常或超时记不确定，
                不在此处重试。正常返回还须校验输出与渠道身份。
                """
                result = await result_reader(state, required=("aggregate",))
                note = next(note for note in result.notifications if note.output_id == oid)
                config = snapshot.channels[cid]
                if not config.enabled:
                    receipt = DeliveryResult(
                        channel_id=cid, output_id=oid, status="skipped", attempts=0
                    )
                elif epoch_key(state, ikey) not in fresh_intents:
                    receipt = uncertain(cid, oid)
                else:
                    try:
                        async with asyncio.timeout(config.timeout):
                            raw = await channel_manager.send(
                                copy_model(config), copy_model(note)
                            )
                        if asyncio.current_task().cancelling():
                            raise asyncio.CancelledError
                        receipt = DeliveryResult.model_validate(
                            raw.model_dump(mode="json")
                            if isinstance(raw, DeliveryResult)
                            else raw
                        )
                        if receipt.channel_id != cid or receipt.output_id != oid:
                            raise ValueError("Delivery identity mismatch")
                    except TimeoutError:
                        receipt = uncertain(cid, oid)
                        receipt.status = "timeout"
                    except Exception:
                        receipt = uncertain(cid, oid)
                return receipt.model_dump(mode="json")

            receipt_archive = archive_node(
                runtime,
                scope="notification",
                stage="notify",
                key=lambda state, key=receipt_key: epoch_key(state, key),
                category=None,
                operation=delivery,
                summarize=lambda body: {
                    "item_status": body["status"], "error": body.get("error"),
                    "output_id": body["output_id"], "channel_id": body["channel_id"],
                },
                publish=lambda key, summary, oid=output_id, cid=cid: {
                    "deliveries": {f"{oid}:{cid}": key},
                },
            )

            async def receipt_node(state, oid=output_id, archived=receipt_archive):
                """对实际存在的冻结输出执行或复用回执节点。"""
                result = await result_reader(state, required=("aggregate",))
                if oid not in result.outputs:
                    return {}
                return await archived(state)

            intent_name, receipt_name = (
                f"intent_{output_index}_{channel_index}",
                f"receipt_{output_index}_{channel_index}",
            )
            graph.add_node(intent_name, safe_node(intent_node))
            graph.add_node(receipt_name, tagged_node(
                registry, ("notify", receipt_name), safe_node(receipt_node), "workflow:delivery",
            ))
            graph.add_edge(START, intent_name)
            graph.add_edge(intent_name, receipt_name)
            receipts.append(receipt_name)
    graph.add_node("arrange", arrange)
    if receipts:
        graph.add_edge(receipts, "arrange")
    else:
        graph.add_edge(START, "arrange")
    graph.add_edge("arrange", END)
    return graph.compile(checkpointer=None)
