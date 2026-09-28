"""Workflow 阶段节点：阶段正文读取、汇合、汇总和终态计算。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from logagent.errors import LogAgentError, exception_error
from logagent.models import (
    AnalysisResult,
    CollectionResult,
    DeliveryResult,
    ErrorInfo,
    ExecutionContext,
    Notification,
    WorkflowSnapshot,
    copy_model,
)
from logagent.workflow.input_processing import process_input
from logagent.workflow.nodes import ArchiveRuntime, archive_node, epoch_key, safe_node

_STAGES = ("collect", "analyze", "aggregate", "notify", "finish")



@dataclass(slots=True)
class WorkflowOperations:
    runtime: ArchiveRuntime
    snapshot: WorkflowSnapshot
    collector_manager: object
    ai_service: object
    channel_manager: object
    context: object | None = None

    async def result(self, state, *, required=()):
        from logagent.workflow.service import WorkflowResult
        result = WorkflowResult(session_id=self.runtime.session_id, workflow_id=self.snapshot.workflow.id)
        for stage in _STAGES:
            key = state.get("phases", {}).get(stage)
            if not key:
                continue
            try:
                body = await self.runtime.read(key)
            except LogAgentError as exc:
                if stage in required or exc.code != "recovery_unavailable":
                    raise
                continue
            errors = body.pop("errors", [])
            result = WorkflowResult.model_validate({
                **result.model_dump(mode="json"), **body, "stage": stage,
                "errors": errors or [e.model_dump(mode="json") for e in result.errors],
            })
        return result

    def _saved_result(self, stage, operation):
        """结果引用提交是图节点的共同边界，不承担阶段分派。"""
        categories = {"collect": "collection", "analyze": "analysis", "aggregate": "final"}

        def summarize(body):
            return {
                "stopped": body.get("stopped", False),
                "status": body.get("status", "running"),
                "error": (body.get("errors") or [None])[-1],
                **({"outputs_available": bool(body.get("outputs")),
                    "fan_in": self.snapshot.workflow.fan_in is not None}
                   if stage == "aggregate" else {}),
            }

        return safe_node(archive_node(
            self.runtime, scope="phase", stage=stage,
            key=lambda state: epoch_key(state, f"phase:{stage}"), operation=operation,
            category=categories.get(stage), summarize=summarize,
            publish=lambda key, summary: {
                "phases": {stage: key}, "stopped": summary["stopped"],
                "status": summary["status"],
            },
        ))

    def collection_result_node(self):
        async def arrange(state):
            from logagent.workflow.service import WorkflowResult
            incoming = WorkflowResult(session_id=self.runtime.session_id,
                                      workflow_id=self.snapshot.workflow.id)
            incoming.collection = [
                CollectionResult.model_validate(await self.runtime.read(state["items"][ident]))
                for ident in self.snapshot.workflow.sources
            ]
            return self._arrange_collection(incoming, self.snapshot)
        return self._saved_result("collect", arrange)

    def analysis_result_node(self):
        async def arrange(state):
            incoming = await self.result(state, required=("collect",))
            incoming.analyses = [
                AnalysisResult.model_validate(await self.runtime.read(state["items"][task.id]))
                for task in self.snapshot.workflow.analyses
            ]
            return self._arrange_analysis(incoming, self.snapshot)
        return self._saved_result("analyze", arrange)

    def aggregate_node(self):
        async def aggregate(state):
            fan_in = self.snapshot.workflow.fan_in
            required = ("analyze",)
            if fan_in and "$input" in fan_in.ordered_inputs(self.snapshot.workflow.analyses):
                required = ("collect", "analyze")
            incoming = await self.result(state, required=required)
            incoming.stage = "aggregate"
            return await self._aggregate(incoming, self.snapshot)
        return self._saved_result("aggregate", aggregate)

    def notification_result_node(self):
        async def arrange(state):
            incoming = await self.result(state, required=("aggregate",))
            return await self._notify(incoming, self.snapshot, self.runtime, state)
        return self._saved_result("notify", arrange)

    def finish_node(self):
        async def finish(state):
            incoming = await self.result(state)
            return await self._finish(incoming, self.runtime, state)
        return self._saved_result("finish", finish)

    @staticmethod
    def _halt(result, code, message):
        """将本次结果标记为失败并阻止下游，同时追加明确的策略错误。"""
        result.stopped, result.status = True, "failed"
        result.errors.append(ErrorInfo(code=code, message=message))

    def _arrange_collection(self, result, snapshot):
        """按来源顺序拼接成功正文，再应用各来源策略和全空策略。

        failed/timeout 共用 on_error，其余非成功状态使用对应策略；
        全空 skip 只停止下游，是否降级由 finish 根据原始结果判断。
        """
        wf = snapshot.workflow
        limited = wf.input_processing.total_tokens is not None or any(
            source.limits.item_tokens or source.limits.field_tokens
            for source in snapshot.sources.values()
        )
        counters = []
        if limited:
            consumers = {(task.ai, task.model) for task in wf.analyses}
            fan = wf.fan_in
            if fan and "$input" in fan.ordered_inputs(wf.analyses):
                reused = fan.reused_task(wf.analyses)
                if reused:
                    consumers.add((reused.ai, reused.model))
                elif fan.ai:
                    consumers.add((fan.ai, fan.model))
            if not hasattr(self.ai_service, "input_counter"):
                raise LogAgentError("tokenizer_unavailable", "AI 服务未提供精确输入 token 计量")
            counters = [self.ai_service.input_counter(snapshot.ai[ai], model)
                        for ai, model in sorted(consumers)]
        result.shared_input, result.input_views = process_input(snapshot, result.collection, counters)
        valid = [view for view in result.input_views if view.status == "success" and not view.omitted]
        for view in result.input_views:
            if view.status == "failed":
                result.errors.append(view.error)
                if snapshot.sources[view.source_id].on_error == "stop":
                    self._halt(result, "input_processing_stopped", "输入处理失败，来源策略要求停止")
        for item in result.collection:
            if item.status == "success":
                continue
            policy = "error" if item.status in {"failed", "timeout", "cancelled", "unknown"} else item.status
            if getattr(snapshot.sources[item.source_id], "on_" + policy) == "stop":
                self._halt(result, "collection_stopped", "来源策略要求停止下游阶段")
                break
        if not valid and not result.stopped:
            if wf.on_all_empty == "stop":
                self._halt(result, "all_empty", "所有来源均无有效内容")
            else:
                result.stopped = True
        return {
            "collection": [item.model_dump(mode="json") for item in result.collection],
            "shared_input": result.shared_input,
            "input_views": [view.model_dump(mode="json") for view in result.input_views],
            "stopped": result.stopped,
            "status": result.status,
            "errors": [e.model_dump(mode="json") for e in result.errors],
        }

    def _arrange_analysis(self, result, snapshot):
        """保留所有分支结果，并按失败策略及部分发送开关决定是否停止下游。"""
        wf = snapshot.workflow
        failed = [item for item in result.analyses if item.status != "success"]
        if len(failed) == len(result.analyses) or (
            failed and (wf.analysis_failure == "stop" or not wf.send_partial)
        ):
            self._halt(result, "analysis_stopped", "分析失败策略阻止下游阶段")
        return {
            "analyses": [item.model_dump(mode="json") for item in result.analyses],
            "stopped": result.stopped,
            "status": result.status,
            "errors": [e.model_dump(mode="json") for e in result.errors],
        }

    async def _analysis_call(self, config, item, text, task_id, result, model):
        """执行一次带超时的 AI 服务调用，校验结果身份并保留取消传播。

        超时及普通异常转换为 AnalysisResult，具体重试由注入的 AI 服务负责。
        """
        try:
            async with asyncio.timeout(config.timeout):
                workflow = self.snapshot.workflow
                kwargs = {"model": model, "task_id": task_id, "context": ExecutionContext(
                    workflow_id=result.workflow_id, session_id=result.session_id, stage=result.stage,
                ), "system_prompt": (
                    workflow.system_prompt if item.system_prompt is None else item.system_prompt
                ), "user_prompt": item.user_prompt}
                input_prompt = (
                    workflow.input_prompt if item.input_prompt is None else item.input_prompt
                )
                raw = await self.ai_service.execute(copy_model(config), input_prompt, text, **kwargs)
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError
            output = AnalysisResult.model_validate(
                raw.model_dump(mode="json") if isinstance(raw, AnalysisResult) else raw
            )
            if output.task_id != task_id:
                raise ValueError("Analysis identity mismatch")
            return output
        except TimeoutError:
            return AnalysisResult(
                task_id=task_id,
                status="timeout",
                error=ErrorInfo(code="ai_timeout", message="AI 调用超时"),
            )
        except Exception as exc:
            return AnalysisResult(
                task_id=task_id,
                status="failed",
                error=exception_error(exc, code="ai_failed", message="AI 调用失败"),
            )

    async def _aggregate(self, result, snapshot):
        """生成通知前的冻结输出：成功分支分别输出，或按 fan-in 顺序汇总。

        汇总可插入完整共享输入及缺失标记，也可再调用指定 AI。
        AI 汇总失败时停止，不改用拼接文本或分支输出替代。
        """
        wf = snapshot.workflow
        if wf.fan_in is None:
            result.outputs = {
                item.task_id: item.text for item in result.analyses if item.status == "success"
            }
        else:
            by_id = {item.task_id: item for item in result.analyses}
            parts = []
            for key in wf.fan_in.ordered_inputs(wf.analyses):
                if key == "$input":
                    parts.append(result.shared_input)
                elif by_id[key].status == "success":
                    parts.append(by_id[key].text)
                elif wf.fan_in.mark_incomplete:
                    parts.append(f"[{key}: incomplete]")
            text = wf.fan_in.separator.join(parts)
            reused = wf.fan_in.reused_task(wf.analyses)
            ai_id = reused.ai if reused else wf.fan_in.ai
            model = reused.model if reused else wf.fan_in.model
            if not text.strip():
                self._halt(result, "aggregate_empty", "汇总未产生有效正文")
            elif ai_id:
                result.aggregate = await self._analysis_call(
                    snapshot.ai[ai_id], wf.fan_in, text, "final", result, model
                )
                if result.aggregate.status != "success":
                    self._halt(result, "aggregate_failed", "AI 汇总失败")
                else:
                    text = result.aggregate.text
            if not result.stopped:
                result.outputs = {"final": text}
        result.notifications = [
            Notification(
                session_id=result.session_id,
                output_id=key,
                title=wf.name or wf.id,
                text=text,
            )
            for key, text in result.outputs.items()
        ]
        return {
            "aggregate": result.aggregate.model_dump(mode="json") if result.aggregate else None,
            "outputs": result.outputs,
            "notifications": [note.model_dump(mode="json") for note in result.notifications],
            "stopped": result.stopped,
            "status": result.status,
            "errors": [e.model_dump(mode="json") for e in result.errors],
        }

    @staticmethod
    def _uncertain(cid, oid):
        """生成投递不确定的失败回执，保留不得自动补发的错误原因。"""
        return DeliveryResult(
            channel_id=cid,
            output_id=oid,
            status="failed",
            attempts=1,
            error=ErrorInfo(
                code="delivery_uncertain",
                message="既有发送未获得可靠回执，不自动补发",
                details={"delivery_uncertain": True},
            ),
        )

    async def _notify(self, result, snapshot, runtime, state):
        """按通知与渠道顺序读取已存回执，形成通知阶段正文，不执行发送。"""
        receipts = []
        for note in result.notifications:
            for cid in snapshot.workflow.channels:
                receipts.append(await runtime.read(
                    state["deliveries"][f"{note.output_id}:{cid}"]
                ))
        return {"deliveries": receipts}

    async def _finish(self, result, runtime, state):
        """汇总最终状态：策略失败优先，否则按局部失败或备份降级判定 partial。

        合法空结果、禁用渠道跳过和主动关闭正文备份本身不构成降级。
        """
        _, entries = await asyncio.to_thread(runtime.store.entries, runtime.session_id)
        phases = set(state["phases"].values())
        retained = {(entry["stage"], entry["summary"].get("execution_epoch"))
                    for entry in entries if entry["write_key"] in phases}
        degraded = any(
            entry["summary"].get("backup_failed") and (
                entry["summary"].get("execution_epoch") == state["execution_epoch"]
                or (entry["stage"], entry["summary"].get("execution_epoch")) in retained
            ) for entry in entries
        )
        degraded |= any(
            item.status in {"failed", "missing", "timeout"} for item in result.collection
        )
        degraded |= any(view.status == "failed" for view in result.input_views)
        degraded |= any(item.status != "success" for item in result.analyses)
        degraded |= any(item.status in {"failed", "timeout", "cancelled", "unknown"} for item in result.deliveries)
        status = "failed" if result.status == "failed" else "partial" if degraded else "completed"
        return {"status": status, "stopped": result.stopped}
