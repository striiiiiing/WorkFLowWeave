"""直接读取内容 state 的业务节点；归档由执行流消费者负责。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

from logagent.errors import exception_error
from logagent.models import AnalysisResult, DeliveryResult, ErrorInfo, ExecutionContext, copy_model
from logagent.workflow.result import collection_input


def phase(state, stage, **changes):
    return {"phase": {"stage": stage, "status": changes.get("status", state.get("status", "running")),
                       "stopped": changes.get("stopped", False), "error": changes.get("error")}, **changes}


@dataclass(slots=True)
class WorkflowOperations:
    snapshot: object
    ai_service: object

    def collection(self, state):
        wf = self.snapshot.workflow
        items = [state["collection_items"][key] for key in wf.sources]
        valid = [item["text"] for item in items if item["status"] == "success"]
        text = collection_input(wf, items)
        error = None
        for item in items:
            if item["status"] == "success":
                continue
            policy = "error" if item["status"] in {"failed", "timeout"} else item["status"]
            if getattr(self.snapshot.sources[item["source_id"]], "on_" + policy) == "stop":
                error = {"code": "collection_stopped", "message": "来源策略要求停止下游阶段"}
                break
        if not valid and wf.on_all_empty == "stop" and not error:
            error = {"code": "all_empty", "message": "所有来源均无有效内容"}
        return phase(state, "collect", shared_input=text, stopped=bool(error) or not valid,
                     status="failed" if error else "running", error=error,
                     degraded=any(i["status"] in {"failed", "missing", "timeout"} for i in items))

    def analysis(self, state):
        wf = self.snapshot.workflow
        items = state["analysis_items"]
        failed = sum(i["status"] != "success" for i in items.values())
        stopped = failed == len(items) or bool(failed and (wf.analysis_failure == "stop" or not wf.send_partial))
        error = {"code": "analysis_stopped", "message": "分析失败策略阻止下游阶段"} if stopped else None
        keep_input = wf.fan_in and "$input" in wf.fan_in.ordered_inputs(wf.analyses)
        return phase(state, "analyze", stopped=stopped, status="failed" if stopped else "running",
                     error=error, degraded=state.get("degraded", False) or bool(failed),
                     shared_input=state["shared_input"] if keep_input else "")

    async def analyze_item(self, state, task):
        context = SimpleNamespace(workflow_id=self.snapshot.workflow.id, session_id=state["session_id"], stage="analyze")
        return await self._analysis_call(self.snapshot.ai[task.ai], task, state["shared_input"], task.id, context, task.model)

    async def aggregate(self, state):
        wf = self.snapshot.workflow
        items = state["analysis_items"]
        outputs, error, model_result = {}, None, None
        if wf.fan_in is None:
            outputs = {t.id: items[t.id]["text"] for t in wf.analyses if items[t.id]["status"] == "success"}
        else:
            parts = []
            for key in wf.fan_in.ordered_inputs(wf.analyses):
                if key == "$input":
                    parts.append(state["shared_input"])
                elif items[key]["status"] == "success":
                    parts.append(items[key]["text"])
                elif wf.fan_in.mark_incomplete:
                    parts.append(f"[{key}: incomplete]")
            text = wf.fan_in.separator.join(parts)
            reused = wf.fan_in.reused_task(wf.analyses)
            ai_id = reused.ai if reused else wf.fan_in.ai
            model = reused.model if reused else wf.fan_in.model
            if not text.strip():
                error = {"code": "aggregate_empty", "message": "汇总未产生有效正文"}
            elif ai_id:
                context = SimpleNamespace(workflow_id=wf.id, session_id=state["session_id"], stage="aggregate")
                result = await self._analysis_call(self.snapshot.ai[ai_id], wf.fan_in, text, "final", context, model)
                model_result = result.model_dump(mode="json", exclude={"text"})
                if result.status != "success":
                    error = {"code": "aggregate_failed", "message": "AI 汇总失败"}
                else:
                    text = result.text
            if not error:
                outputs = {"final": text}
        return phase(state, "aggregate", outputs=outputs, aggregate_meta=model_result,
                     analysis_items={}, shared_input="", stopped=bool(error), error=error,
                     status="failed" if error else "running")

    def notification(self, state):
        degraded = state.get("degraded", False) or any(
            i["status"] in {"failed", "timeout"} for i in state.get("deliveries", {}).values())
        return phase(state, "notify", degraded=degraded)

    def finish(self, state):
        status = "failed" if state["status"] == "failed" else "partial" if state.get("degraded") else "completed"
        return phase(state, "finish", status=status, stopped=state.get("stopped", False), error=state.get("error"))

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

