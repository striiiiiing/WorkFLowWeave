"""将已提交 checkpoint/pending writes 派生为长期事实；不调用业务节点。"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from sqlalchemy.exc import DBAPIError

from logagent.errors import LogAgentError
from logagent.models import WorkflowSnapshot
from logagent.workflow.checkpoints import finish_write
from logagent.workflow.graph import GRAPH_REVISION
from logagent.workflow.stream import progress_layout

logger = logging.getLogger("logagent.workflow.archive")


async def commit(function, *args, **kwargs):
    return await finish_write(asyncio.to_thread(function, *args, **kwargs))


class CheckpointArchive:
    def __init__(self, saver, store, view, publish):
        self.saver, self.store, self.view, self.publish = saver, store, view, publish

    async def reconcile(self, session_id):
        config = {"configurable": {"thread_id": session_id}}
        saved = [item async for item in self.saver.alist(config)]
        roots = [item for item in saved if not item.config["configurable"].get("checkpoint_ns")]
        snapshots = [item.checkpoint["channel_values"] for item in roots
                     if item.checkpoint["channel_values"].get("graph_revision") == GRAPH_REVISION]
        if not snapshots:
            return set()
        latest = snapshots[0]
        snapshot = WorkflowSnapshot.model_validate(latest["snapshot"])
        policy = snapshot.workflow.backup
        await asyncio.to_thread(self.store.create, session_id, snapshot.workflow.id, policy,
                                workflow_name=snapshot.workflow.name)
        confirmed = set()
        epochs = {}
        facts = defaultdict(list)
        stage_order = {"collect": 0, "analyze": 1, "aggregate": 2, "notify": 3, "finish": 4}
        for item in sorted(saved, key=lambda value: value.checkpoint["id"]):
            values = item.checkpoint.get("channel_values", {})
            epoch = values.get("execution_epoch")
            ns = item.config["configurable"].get("checkpoint_ns", "")
            if not epoch or not ns and values.get("graph_revision") != GRAPH_REVISION:
                continue
            if not ns:
                epochs.setdefault(epoch, values)
            groups = defaultdict(dict)
            for task, channel, value in item.pending_writes or ():
                groups[task][channel] = value
            for task, writes in groups.items():
                source = {"checkpoint_id": item.config["configurable"]["checkpoint_id"],
                          "namespace": ns, "task_id": task}
                actual_epoch = writes.get("execution_epoch", epoch)
                if not ns and writes.get("phase", {}).get("stage"):
                    facts[actual_epoch].append((stage_order[writes["phase"]["stage"]], 1, source, "phase", writes))
                for channel, stage in (("collection_items", "collect"), ("analysis_items", "analyze"),
                                       ("intents", "notify"), ("deliveries", "notify")):
                    if ns.split(":", 1)[0] == stage and writes.get(channel):
                        facts[actual_epoch].append((stage_order[stage], 0, source, channel, writes[channel]))
        for epoch, values in epochs.items():
            await self._configuration(session_id, snapshot, values, policy)
            for _, _, source, channel, content in sorted(facts[epoch], key=lambda fact: fact[:2]):
                ns = source["namespace"]
                if channel == "phase":
                    await self._phase(session_id, epoch, content, policy, snapshot, source, values)
                    confirmed.add((epoch, "", "phase", content["phase"]["stage"]))
                    continue
                stage = ns.split(":", 1)[0]
                for ident, body in content.items():
                    if channel in {"collection_items", "analysis_items"}:
                        key, category, scope = f"{stage}:item:{ident}:epoch:{epoch}", "collection" if stage == "collect" else "analysis", stage
                        summary = {"execution_epoch": epoch, "item_id": ident,
                                   "item_status": body["status"], "error": body.get("error")}
                    else:
                        prefix = "intent" if channel == "intents" else "delivery"
                        key, category, scope = f"{prefix}:{ident}:epoch:{epoch}", None, "notification"
                        summary = {"execution_epoch": epoch, "output_id": body["output_id"], "channel_id": body["channel_id"]}
                        if channel == "deliveries":
                            summary.update(item_status=body["status"], error=body.get("error"))
                    provenance = {"configuration": "snapshot", "item_id": ident}
                    if policy.enabled and policy.snapshot and stage == "collect":
                        provenance["source"] = snapshot.sources[ident].model_dump(mode="json")
                    if policy.enabled and policy.snapshot and stage == "analyze":
                        task = next(task for task in snapshot.workflow.analyses if task.id == ident)
                        origin = values.get("stage_origins", {}).get("collect", epoch)
                        provenance.update(task=task.model_dump(mode="json"), ai=snapshot.ai[task.ai].model_dump(mode="json"),
                            prompts=self._prompts(snapshot, task),
                            upstream=[f"collect:item:{key}:epoch:{origin}" for key in snapshot.workflow.sources])
                    await self._write(session_id, key, stage, scope, category, policy, summary, body, source, provenance=provenance)
                    confirmed.add((epoch, ns, channel, ident))
        return confirmed

    async def _configuration(self, sid, snapshot, values, policy):
        epoch = values["execution_epoch"]
        origins = values.get("stage_origins", {})
        refs = {stage: f"phase:{stage}:epoch:{original}" for stage, original in origins.items()}
        await self._write(sid, "snapshot", None, "configuration", "snapshot", policy,
                          {"layout": progress_layout(snapshot)}, {"snapshot": snapshot.model_dump(mode="json")}, None)
        await self._write(sid, f"epoch:{epoch}", values.get("resume_stage") or "collect", "parent", None, policy,
                          {"execution_epoch": epoch, "status": "running", "retained_phases": refs}, None, None)

    async def _phase(self, sid, epoch, writes, policy, snapshot, source, values):
        info = writes["phase"]
        stage = info["stage"]
        summary = {**info, "execution_epoch": epoch}
        body = {key: writes[key] for key in ("status", "stopped", "error", "degraded") if key in writes}
        if stage == "collect":
            body["input_format"] = {"input_separator": snapshot.workflow.input_separator,
                                    "include_counts": snapshot.workflow.include_counts}
        if stage == "aggregate":
            analysis_epoch = values.get("stage_origins", {}).get("analyze", epoch)
            for oid, text in writes.get("outputs", {}).items():
                tasks = snapshot.workflow.analyses
                selected = tasks if snapshot.workflow.fan_in else [task for task in tasks if task.id == oid]
                provenance = {"configuration": "snapshot", "upstream": [f"analyze:item:{task.id}:epoch:{analysis_epoch}" for task in selected]}
                if policy.enabled and policy.snapshot and snapshot.workflow.fan_in:
                    fan = snapshot.workflow.fan_in
                    reused = fan.reused_task(tasks)
                    ai_id = reused.ai if reused else fan.ai
                    provenance.update(fan_in=fan.model_dump(mode="json"), prompts=self._prompts(snapshot, fan),
                                      ai=snapshot.ai[ai_id].model_dump(mode="json") if ai_id else None,
                                      model=reused.model if reused else fan.model)
                await self._write(sid, f"output:{oid}:epoch:{epoch}", stage, "output", "final", policy,
                                  {"execution_epoch": epoch, "output_id": oid}, {"text": text}, source, provenance=provenance)
            summary.update(outputs_available=bool(writes.get("outputs")), fan_in=snapshot.workflow.fan_in is not None)
            body["aggregate_meta"] = writes.get("aggregate_meta")
        await self._write(sid, f"phase:{stage}:epoch:{epoch}", stage, "phase", None, policy, summary, body, source)

    async def _write(self, sid, key, stage, scope, category, policy, summary, body, source, *, provenance=None):
        persist = category is None or policy.enabled and getattr(policy, category)
        before = await asyncio.to_thread(self.store.entry, sid, key)
        try:
            entry = await commit(self.store.write, sid, key, stage=stage, scope=scope,
                summary=summary, body=body if persist else None, category=category,
                availability="available" if persist else "not_saved", source=source, provenance=provenance)
        except (DBAPIError, OSError) as exc:
            if category is None or not persist or body is None:
                raise
            logger.exception("长期正文归档失败，保留源 checkpoint", extra={"session_id": sid, "key": key})
            entry = await commit(self.store.write, sid, f"archive_failed:{key}", stage=stage,
                scope="archive_error", availability="write_failed", summary={**summary,
                    "result_key": key, "result_scope": scope, "result_category": category,
                    "error": {"code": "backup_failed", "message": "长期正文归档失败，源 checkpoint 尚保留"}})
            await self.publish(await self.view.get_session(sid))
            if policy.on_failure == "stop":
                raise LogAgentError("backup_failed", "正文归档失败，备份策略要求停止") from exc
            return entry
        visible = scope in {"collect", "analyze", "parent"} or scope == "phase" and stage in {"aggregate", "finish"} or key.startswith("delivery:")
        if before is None and visible:
            record = await self.view.get_session(sid)
            await self.publish(record)
        return entry

    @staticmethod
    def _prompts(snapshot, item):
        return {"system_prompt": snapshot.workflow.system_prompt if item.system_prompt is None else item.system_prompt,
                "input_prompt": snapshot.workflow.input_prompt if item.input_prompt is None else item.input_prompt,
                "user_prompt": item.user_prompt}

    async def consume(self, session_id, graph, state, config):
        # One producer, one consumer; the existing observation capacity bounds hints.
        from logagent.workflow.stream import SUBSCRIBER_CAPACITY
        epoch = state["execution_epoch"] if state else (await graph.aget_state(config)).values["execution_epoch"]
        queue = asyncio.Queue(maxsize=SUBSCRIBER_CAPACITY)
        async def drive():
            async for namespace, update in graph.astream(state, config, durability="sync", subgraphs=True, stream_mode="updates"):
                await queue.put((namespace, update))
            await queue.put(None)
        producer = asyncio.create_task(drive(), name=f"workflow-stream:{session_id}")
        get = None
        try:
            while True:
                get = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait((get, producer), return_when=asyncio.FIRST_COMPLETED)
                if producer in done and producer.exception() is not None:
                    get.cancel()
                    await asyncio.gather(get, return_exceptions=True)
                    producer.result()
                chunk = await get
                if chunk is None:
                    break
                namespace, update = chunk
                ns = "|".join(namespace)
                expected = set()
                for changes in update.values():
                    if not isinstance(changes, dict):
                        continue
                    for channel in ("collection_items", "analysis_items", "intents", "deliveries"):
                        if ns:
                            expected.update((epoch, ns, channel, key) for key in changes.get(channel, {}))
                    if not ns and changes.get("phase"):
                        expected.add((epoch, ns, "phase", changes["phase"]["stage"]))
                while True:
                    found = await self.reconcile(session_id)
                    if expected <= found:
                        break
                    if producer.done():
                        producer.result()
                        raise LogAgentError("archive_unconfirmed", "执行流已结束但结果缺少持久化证据")
                    await asyncio.sleep(0)
            await producer
            await self.reconcile(session_id)
        finally:
            if get is not None and not get.done():
                get.cancel()
                await asyncio.gather(get, return_exceptions=True)
            if not producer.done():
                producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
