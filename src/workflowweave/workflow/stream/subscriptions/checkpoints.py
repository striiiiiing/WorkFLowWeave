"""将已提交 checkpoint/pending writes 派生为长期事实；不调用业务节点。"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from langgraph.types import Overwrite
from sqlalchemy.exc import DBAPIError

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import WorkflowSnapshot
from workflowweave.workflow.graph.workflow import GRAPH_REVISION
from workflowweave.workflow.storage.checkpoints import finish_write
from workflowweave.workflow.storage.progress import progress_layout

logger = logging.getLogger("workflowweave.workflow.stream.subscriptions.checkpoints")


async def commit(function, *args, **kwargs):
    return await finish_write(asyncio.to_thread(function, *args, **kwargs))


class CheckpointArchive:
    def __init__(self, saver, store, view, publish):
        self.saver, self.store, self.view, self.publish = saver, store, view, publish

    async def reconcile(self, session_id):
        """Only recovery, settlement and deferred handoff scan history; never per event."""
        saved = [
            item async for item in self.saver.alist({"configurable": {"thread_id": session_id}})
        ]
        roots = [
            item.checkpoint["channel_values"]
            for item in saved
            if not item.config["configurable"].get("checkpoint_ns")
            and item.checkpoint["channel_values"].get("graph_revision") == GRAPH_REVISION
        ]
        if not roots:
            return
        snapshot = WorkflowSnapshot.model_validate(
            roots[0]["snapshot"], context={"historical_snapshot": True}
        )
        epochs = {values["execution_epoch"]: values for values in roots}
        for item in sorted(saved, key=lambda item: item.checkpoint["id"]):
            values = item.checkpoint["channel_values"]
            epoch = values.get("execution_epoch")
            if epoch not in epochs:
                continue
            await self.checkpoint(session_id, snapshot, epochs[epoch], item)
            # A process can exit after successful task writes but before the
            # next checkpoint. Recover those durable facts without rerunning it.
            groups = defaultdict(dict)
            for task, channel, value in item.pending_writes or ():
                if channel == "execution_epoch" and isinstance(value, Overwrite):
                    value = value.value
                groups[task][channel] = value
            for task, writes in groups.items():
                actual_epoch = writes.get("execution_epoch", epoch)
                if actual_epoch not in epochs:
                    continue
                source = self._source(item, task)
                await self.values(
                    session_id, snapshot, epochs[actual_epoch], {**values, **writes}, source
                )

    @staticmethod
    def _source(saved, task_id=""):
        coordinates = saved.config["configurable"]
        return {
            "checkpoint_id": coordinates["checkpoint_id"],
            "namespace": coordinates.get("checkpoint_ns", ""),
            "task_id": task_id,
        }

    async def checkpoint(self, sid, snapshot, epoch_values, saved):
        """Archive an already persisted checkpoint, using existing fact transactions."""
        await self.values(
            sid, snapshot, epoch_values, saved.checkpoint["channel_values"], self._source(saved)
        )

    async def values(self, sid, snapshot, epoch_values, values, source):
        epoch = values.get("execution_epoch")
        if not epoch:
            return
        policy = snapshot.workflow.backup
        await asyncio.to_thread(
            self.store.create,
            sid,
            snapshot.workflow.id,
            policy,
            workflow_name=snapshot.workflow.name,
        )
        await self._configuration(sid, snapshot, epoch_values, policy)
        namespace = source["namespace"]
        if not namespace:
            if values.get("graph_revision") != GRAPH_REVISION:
                return
            if values.get("phase", {}).get("stage"):
                await self._phase(sid, epoch, values, policy, snapshot, source, epoch_values)
            return
        stage = namespace.split(":", 1)[0]
        if stage == "aggregate" and values.get("phase", {}).get("stage") == stage:
            await self._phase(sid, epoch, values, policy, snapshot, source, epoch_values)
            return
        for channel, owner in (
            ("collection_items", "collect"),
            ("analysis_items", "analyze"),
            ("intents", "notify"),
            ("deliveries", "notify"),
        ):
            if stage != owner:
                continue
            for ident, body in values.get(channel, {}).items():
                await self._item(sid, snapshot, epoch_values, stage, channel, ident, body, source)

    async def running(self, sid, snapshot, values, *, stage, source, item_id=None,
                      output_id=None, channel_id=None):
        """Persist a committed-view placeholder for work that has just started.

        Start events do not contain business results, so they use separate stable
        keys and pending availability. The corresponding checkpoint fact later
        replaces this projection in ``project_progress`` without mutating history.
        """
        epoch = values.get("execution_epoch")
        if not epoch:
            return
        policy = snapshot.workflow.backup
        if item_id is not None:
            key = f"progress:{stage}:item:{item_id}:epoch:{epoch}"
            scope = stage
            summary = {
                "execution_epoch": epoch,
                "item_id": item_id,
                "item_status": "running",
            }
        elif output_id is not None and channel_id is not None:
            key = f"progress:delivery:{output_id}:{channel_id}:epoch:{epoch}"
            scope = "notification"
            summary = {
                "execution_epoch": epoch,
                "output_id": output_id,
                "channel_id": channel_id,
                "item_status": "running",
            }
        else:
            key = f"phase:{stage}:start:epoch:{epoch}"
            scope = "phase"
            summary = {
                "execution_epoch": epoch,
                "stage": stage,
                "status": "running",
                "progress_status": "running",
            }
        await self._write(
            sid,
            key,
            stage,
            scope,
            None,
            policy,
            summary,
            None,
            source,
            availability="pending",
            publish=True,
        )

    async def _item(self, sid, snapshot, values, stage, channel, ident, body, source):
        epoch = values["execution_epoch"]
        policy = snapshot.workflow.backup
        if channel in {"collection_items", "analysis_items"}:
            key = f"{stage}:item:{ident}:epoch:{epoch}"
            category, scope = "collection" if stage == "collect" else "analysis", stage
            summary = {
                "execution_epoch": epoch,
                "item_id": ident,
                "item_status": body["status"],
                "error": body.get("error"),
            }
        else:
            prefix = "intent" if channel == "intents" else "delivery"
            key, category, scope = f"{prefix}:{ident}:epoch:{epoch}", None, "notification"
            summary = {
                "execution_epoch": epoch,
                "output_id": body["output_id"],
                "channel_id": body["channel_id"],
            }
            if channel == "deliveries":
                summary.update(item_status=body["status"], error=body.get("error"))
        provenance = {"configuration": "snapshot", "item_id": ident}
        if policy.enabled and policy.snapshot and stage == "collect":
            provenance["source"] = snapshot.sources[ident].model_dump(mode="json")
        if policy.enabled and policy.snapshot and stage == "analyze":
            task = next(task for task in snapshot.workflow.analyses if task.id == ident)
            origin = values.get("stage_origins", {}).get("collect", epoch)
            provenance.update(
                task=task.model_dump(mode="json"),
                ai=snapshot.ai[task.ai].model_dump(mode="json"),
                prompts=self._prompts(snapshot, task),
                upstream=[
                    f"collect:item:{key}:epoch:{origin}" for key in snapshot.workflow.sources
                ],
            )
        await self._write(
            sid, key, stage, scope, category, policy, summary, body, source, provenance=provenance
        )

    async def _configuration(self, sid, snapshot, values, policy):
        epoch = values["execution_epoch"]
        origins = values.get("stage_origins", {})
        refs = {stage: f"phase:{stage}:epoch:{original}" for stage, original in origins.items()}
        await self._write(
            sid,
            "snapshot",
            None,
            "configuration",
            "snapshot",
            policy,
            {"layout": progress_layout(snapshot)},
            {"snapshot": values["snapshot"]},
            None,
        )
        await self._write(
            sid,
            f"epoch:{epoch}",
            values.get("resume_stage") or "collect",
            "parent",
            None,
            policy,
            {"execution_epoch": epoch, "status": "running", "retained_phases": refs},
            None,
            None,
        )

    async def _phase(self, sid, epoch, writes, policy, snapshot, source, values):
        info = writes["phase"]
        stage = info["stage"]
        summary = {**info, "execution_epoch": epoch}
        body = {
            key: writes[key] for key in ("status", "stopped", "error", "degraded") if key in writes
        }
        if stage == "collect":
            body["shared_input"] = writes.get("shared_input", "")
            body["input_views"] = writes.get("input_views", [])
            body["input_format"] = {
                "input_separator": snapshot.workflow.input_separator,
                "include_counts": snapshot.workflow.include_counts,
            }
        if stage == "aggregate":
            analysis_epoch = values.get("stage_origins", {}).get("analyze", epoch)
            for oid, text in writes.get("outputs", {}).items():
                tasks = snapshot.workflow.analyses
                selected = (
                    tasks
                    if snapshot.workflow.fan_in
                    else [task for task in tasks if task.id == oid]
                )
                provenance = {
                    "configuration": "snapshot",
                    "upstream": [
                        f"analyze:item:{task.id}:epoch:{analysis_epoch}" for task in selected
                    ],
                }
                if policy.enabled and policy.snapshot and snapshot.workflow.fan_in:
                    fan = snapshot.workflow.fan_in
                    reused = fan.reused_task(tasks)
                    ai_id = reused.ai if reused else fan.ai
                    provenance.update(
                        fan_in=values["snapshot"]["workflow"]["fan_in"],
                        prompts=self._prompts(snapshot, fan),
                        ai=snapshot.ai[ai_id].model_dump(mode="json") if ai_id else None,
                        model=reused.model if reused else fan.model,
                    )
                await self._write(
                    sid,
                    f"output:{oid}:epoch:{epoch}",
                    stage,
                    "output",
                    "final",
                    policy,
                    {"execution_epoch": epoch, "output_id": oid},
                    {"text": text},
                    source,
                    provenance=provenance,
                )
            summary.update(
                outputs_available=bool(writes.get("outputs")),
                fan_in=snapshot.workflow.fan_in is not None,
            )
            body["aggregate_meta"] = writes.get("aggregate_meta")
        await self._write(
            sid, f"phase:{stage}:epoch:{epoch}", stage, "phase", None, policy, summary, body, source
        )

    async def _write(
        self,
        sid,
        key,
        stage,
        scope,
        category,
        policy,
        summary,
        body,
        source,
        *,
        provenance=None,
        availability=None,
        publish=False,
    ):
        persist = category is None or policy.enabled and getattr(policy, category)
        before = await asyncio.to_thread(self.store.entry, sid, key)
        entry_availability = availability or ("available" if persist else "not_saved")
        if before is not None:
            # The storage transaction may have committed immediately before a
            # worker/process interruption was reported.  Stable business keys
            # make that immutable fact the recovery authority; replay must not
            # call the wrapped writer again (a failure injector or a dead
            # process can otherwise turn a committed fact into a second
            # failure).  ``entry`` already validates the digest and body.
            checked = await asyncio.to_thread(
                self.store.existing_write,
                sid,
                key,
                stage=stage,
                scope=scope,
                summary=summary,
                body=body if persist else None,
                availability=entry_availability,
                category=category,
            )
            if checked is None:
                # The entry disappeared between the inexpensive existence
                # probe and the digest-checked read; let the normal write path
                # establish it again rather than returning a stale projection.
                before = None
            else:
                if source:
                    await asyncio.to_thread(self.store.record_source, sid, key, source)
                return checked
        try:
            entry = await commit(
                self.store.write,
                sid,
                key,
                stage=stage,
                scope=scope,
                summary=summary,
                body=body if persist else None,
                category=category,
                availability=entry_availability,
                source=source,
                provenance=provenance,
            )
        except (DBAPIError, OSError) as exc:
            if category is None or not persist or body is None:
                raise
            logger.exception(
                "长期正文归档失败，保留源 checkpoint", extra={"session_id": sid, "key": key}
            )
            entry = await commit(
                self.store.write,
                sid,
                f"archive_failed:{key}",
                stage=stage,
                scope="archive_error",
                availability="write_failed",
                summary={
                    **summary,
                    "result_key": key,
                    "result_scope": scope,
                    "result_category": category,
                    "error": {
                        "code": "backup_failed",
                        "message": "长期正文归档失败，源 checkpoint 尚保留",
                    },
                },
            )
            await self.publish(await self.view.get_session(sid))
            if policy.on_failure == "stop":
                raise WorkFLowWeaveError("backup_failed", "正文归档失败，备份策略要求停止") from exc
            return entry
        visible = (
            scope in {"collect", "analyze", "parent"}
            or scope == "phase"
            and stage in {"aggregate", "finish"}
            or key.startswith("delivery:")
        )
        if before is None and (visible or publish):
            record = await self.view.get_session(sid)
            await self.publish(record)
        return entry

    @staticmethod
    def _prompts(snapshot, item):
        return {
            "system_prompt": snapshot.workflow.system_prompt
            if item.system_prompt is None
            else item.system_prompt,
            "input_prompt": snapshot.workflow.input_prompt
            if item.input_prompt is None
            else item.input_prompt,
            "user_prompt": item.user_prompt,
        }


class CheckpointSubscription:
    def __init__(self, archive, snapshot, values, context=None):
        self.archive = archive
        self.snapshot = snapshot
        self.values = values
        self.context = context
        self._running_keys = set()

    async def __call__(self, event):
        await self._observe_start(event)
        # Only the root graph forwards the complete (namespace, mode, payload)
        # stream. Descendant Runnable callbacks also inherit business tags.
        if event["event"] != "on_chain_stream" or event["parent_ids"]:
            return
        namespace, mode, payload = event["data"]["chunk"]
        if mode != "checkpoints":
            return
        metadata = payload["metadata"]
        # Input/entry projections can precede persistence. Loop checkpoints
        # following a completed step pass LangGraph's sync durability barrier.
        if metadata["source"] != "loop" or metadata["step"] < 1:
            return
        session_id = event["metadata"]["sessionID"]
        coordinates = payload["config"]["configurable"]
        if coordinates["thread_id"] != session_id or coordinates["checkpoint_ns"] != "|".join(
            namespace
        ):
            raise ValueError("Workflow checkpoint event identity mismatch")
        # Sync loop events carry the committed projection. A deferred cleanup
        # may already have removed its source by the time this queue is drained.
        # Consume the immutable event payload rather than querying a deleted row.
        values = {"execution_epoch": self.values["execution_epoch"], **payload["values"]}
        if not namespace:
            self.values = values
        source = {
            "checkpoint_id": coordinates["checkpoint_id"],
            "namespace": coordinates["checkpoint_ns"],
            "task_id": "",
        }
        await self.archive.values(session_id, self.snapshot, self.values, values, source)
        if self.context and source["namespace"].split(":", 1)[0] == "notify":
            for key in values.get("intents", {}):
                self.context.confirm_intent(values["execution_epoch"], key)

    async def _observe_start(self, event):
        if event.get("event") != "on_chain_start":
            return
        metadata = event.get("metadata") or {}
        namespace = metadata.get("langgraph_checkpoint_ns", "")
        node = metadata.get("langgraph_node")
        if not node or not namespace:
            return
        session_id = event.get("metadata", {}).get("sessionID")
        epoch = self.values.get("execution_epoch")
        if not session_id or not epoch:
            return
        source = {
            "checkpoint_id": metadata.get("langgraph_checkpoint_id", ""),
            "namespace": namespace,
            "task_id": event.get("run_id", ""),
        }
        if "|" not in namespace and node in {
            "collect",
            "analyze",
            "aggregate",
            "notify",
            "finish",
        }:
            await self._mark_running(session_id, epoch, stage=node, source=source)
            return
        if node == "item":
            payload = event.get("data", {}).get("input") or {}
            item_id = payload.get("source_id") or payload.get("analysis_id")
            stage = "collect" if item_id and "source_id" in payload else "analyze"
            if item_id:
                await self._mark_running(
                    session_id, epoch, stage=stage, item_id=item_id, source=source
                )
        elif node == "delivery":
            payload = event.get("data", {}).get("input") or {}
            if payload.get("output_id") and payload.get("channel_id"):
                await self._mark_running(
                    session_id,
                    epoch,
                    stage="notify",
                    output_id=payload["output_id"],
                    channel_id=payload["channel_id"],
                    source=source,
                )

    async def _mark_running(self, session_id, epoch, *, stage, source, item_id=None,
                            output_id=None, channel_id=None):
        identity = (epoch, stage, item_id, output_id, channel_id)
        if identity in self._running_keys:
            return
        self._running_keys.add(identity)
        try:
            await self.archive.running(
                session_id,
                self.snapshot,
                self.values,
                stage=stage,
                item_id=item_id,
                output_id=output_id,
                channel_id=channel_id,
                source=source,
            )
        except BaseException:
            self._running_keys.discard(identity)
            raise
