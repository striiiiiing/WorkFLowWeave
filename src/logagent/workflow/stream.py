"""消费本次图更新并发布已提交的业务引用；订阅者不持有执行器。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from logagent.models import WorkflowProgress

# 每个观察者只保留有限业务更新；满队列显式要求重连，不丢事件后假装同步。
SUBSCRIBER_CAPACITY = 64


def progress_layout(snapshot):
    wf = snapshot.workflow
    items = [dict(stage="collect", event="item", item_id=key,
                  label=snapshot.sources[key].display_name or key) for key in wf.sources]
    items += [dict(stage="analyze", event="item", item_id=task.id,
                   label=task.id) for task in wf.analyses]
    items.append(dict(stage="aggregate", event="aggregate", label="最终报告"))
    outputs = ["final"] if wf.fan_in else [task.id for task in wf.analyses]
    items += [dict(stage="notify", event="delivery", output_id=oid, channel_id=cid,
                   label=cid)
              for oid in outputs for cid in wf.channels]
    return [{**item, "order": order} for order, item in enumerate(items)]


def identity(item):
    return (item.stage, item.event, item.item_id, item.output_id, item.channel_id)


def entry_progress(entry):
    """查询与流消费共用同一条目映射。"""
    summary = entry["summary"]
    scope, stage = entry["scope"], entry["stage"]
    if scope in {"collect", "analyze"}:
        event, status = "item", summary["item_status"]
    elif scope == "notification" and entry["write_key"].startswith("delivery:"):
        event, status = "delivery", summary["item_status"]
        if (summary.get("error") or {}).get("code") == "delivery_uncertain":
            status = "delivery_uncertain"
    elif scope == "phase" and stage == "aggregate":
        event = "aggregate"
        status = "failed" if summary.get("stopped") else "success"
    elif scope == "parent" or (scope == "phase" and stage == "finish"):
        if "status" not in summary:
            return None
        event, status = "lifecycle", summary["status"]
    else:
        return None
    return WorkflowProgress(
        session_id=entry["session_id"], execution_epoch=summary.get("execution_epoch"),
        stage=stage, event=event, status=status,
        item_id=summary.get("item_id"), output_id=summary.get("output_id"),
        channel_id=summary.get("channel_id"), result_ref=entry["write_key"],
        version=entry["version"], availability=entry["availability"], error=summary.get("error"),
        summary={key: summary[key] for key in ("fan_in", "outputs_available") if key in summary},
    )


def active_phases(entries):
    """查询只采用执行入口实际保留的引用，包括显式选择的旧历史入口。"""
    indexed, phases = {}, {}
    for entry in entries:
        if entry["write_key"].startswith("epoch:"):
            phases = {stage: indexed[ref] for stage, ref in entry["summary"].get("retained_phases", {}).items() if ref in indexed}
        if entry["scope"] == "phase":
            phases[entry["stage"]] = entry
        indexed[entry["write_key"]] = entry
    return phases


def project_progress(session_id, entries):
    """固定版本和所选入口引用共同决定投影，不混入其他轮次的上游结果。"""
    items, epoch = {}, None
    for entry in entries:
        if entry["write_key"] == "snapshot":
            epoch = entry["summary"].get("execution_epoch")
            for metadata in entry["summary"].get("layout", []):
                item = WorkflowProgress(session_id=session_id, status="pending", **metadata)
                items[identity(item)] = item
        if entry["write_key"].startswith("epoch:"):
            epoch = entry["summary"]["execution_epoch"]
    phases = active_phases(entries)
    retained_epochs = {stage: entry["summary"].get("execution_epoch")
                       for stage, entry in phases.items()}
    for entry in entries:
        event = entry_progress(entry)
        if event is None or event.event == "lifecycle":
            continue
        if (event.execution_epoch != epoch
                and event.execution_epoch != retained_epochs.get(event.stage)):
            continue
        key = identity(event)
        if key in items:
            event.label = items[key].label
            event.order = items[key].order
        items[key] = event
    for item in items.values():
        item.execution_epoch = epoch
        if "finish" in phases and item.status == "pending":
            item.status = "skipped"
    return epoch, list(items.values())


class ProgressHub:
    """仅有界传输，不维护第二份业务状态或持久化日志。"""

    def __init__(self, *, capacity=SUBSCRIBER_CAPACITY):
        self.capacity = capacity
        self.subscribers = {}

    @asynccontextmanager
    async def subscribe(self, session_id):
        queue = asyncio.Queue(maxsize=self.capacity)
        group = self.subscribers.setdefault(session_id, set())
        group.add(queue)
        try:
            yield queue
        finally:
            group.discard(queue)
            if not group:
                self.subscribers.pop(session_id, None)

    async def publish(self, event):
        for queue in tuple(self.subscribers.get(event.session_id, ())):
            if queue.full():
                # 清空只为了放入明确的失同步信号；此连接不再接收业务更新。
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
                self.subscribers[event.session_id].discard(queue)
            else:
                queue.put_nowait(event)

    async def close(self):
        for group in self.subscribers.values():
            for queue in group:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
        self.subscribers.clear()


def tagged_node(registry, path, operation, tag):
    """图装配时同时注册标签与公开 updates 的节点定位，避免两套分类表。"""
    from langchain_core.runnables import RunnableLambda

    registry[path] = tag
    return RunnableLambda(operation).with_config(tags=[tag])
