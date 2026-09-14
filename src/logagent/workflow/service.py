"""In-memory workflow orchestration built on LangGraph.

The service deliberately keeps all execution state in the invocation. Dependencies are
injected and may expose either the concrete managers or small protocol-compatible mocks.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from logagent.errors import LogAgentError, exception_error
from logagent.models import (
    AnalysisResult, CollectionContext, CollectionResult, DeliveryResult,
    ErrorInfo, Notification, WorkflowDefinition, WorkflowSnapshot,
)

logger = logging.getLogger("logagent.workflow")


@dataclass
class WorkflowResult:
    session_id: str
    workflow_id: str
    stage: str = "finish"
    collection: list[CollectionResult] = field(default_factory=list)
    analyses: list[AnalysisResult] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    notifications: list[Notification] = field(default_factory=list)
    deliveries: list[DeliveryResult] = field(default_factory=list)
    stopped: bool = False
    cancelled: bool = False
    errors: list[ErrorInfo] = field(default_factory=list)

    @property
    def collection_results(self): return self.collection
    @property
    def analysis_results(self): return self.analyses
    def model_dump(self, **_: Any) -> dict[str, Any]:
        return {
            "session_id": self.session_id, "workflow_id": self.workflow_id, "stage": self.stage,
            "collection": [x.model_dump(mode="python") for x in self.collection],
            "analyses": [x.model_dump(mode="python") for x in self.analyses],
            "outputs": self.outputs,
            "notifications": [x.model_dump(mode="python") for x in self.notifications],
            "deliveries": [x.model_dump(mode="python") for x in self.deliveries],
            "stopped": self.stopped, "cancelled": self.cancelled,
            "errors": [x.model_dump(mode="python") for x in self.errors],
        }


class _State(TypedDict, total=False):
    snapshot: WorkflowSnapshot
    session_id: str
    context: CollectionContext
    result: WorkflowResult
    stopped: bool
    cancelled: bool
    shared_input: str
    analysis_map: dict[str, AnalysisResult]
    outputs: dict[str, str]


async def _maybe_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a mock with a tolerant signature (the public manager boundary is small)."""
    try:
        value = fn(*args, **kwargs)
    except TypeError:
        # Try common reduced signatures used by test doubles.
        for a in (args[:2], args[1:], args[:1], (args[-1],)):
            try:
                value = fn(*a)
                break
            except TypeError:
                continue
        else:
            raise
    return await value if inspect.isawaitable(value) else value


def _error(exc: Exception, code: str, message: str) -> ErrorInfo:
    return exception_error(exc, code=code, message=message)


class RunCoordinator:
    def __init__(self, *, max_concurrent_runs: int = 4) -> None:
        self._capacity = asyncio.Semaphore(max_concurrent_runs)
        self._max = max_concurrent_runs
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()
        self._admission_lock = asyncio.Lock()
        self._active_count = 0

    @property
    def active(self) -> int: return len(self._tasks)

    async def acquire(self, session_id: str) -> None:
        # Capacity exhaustion is an immediate admission failure.
        async with self._admission_lock:
            if self._active_count >= self._max:
                raise LogAgentError("capacity_exhausted", "运行容量已满")
            self._active_count += 1
        await self._capacity.acquire()
        async with self._lock:
            self._tasks[session_id] = asyncio.current_task()  # type: ignore[assignment]

    async def release(self, session_id: str) -> None:
        async with self._lock:
            self._tasks.pop(session_id, None)
        self._capacity.release()
        async with self._admission_lock:
            self._active_count = max(0, self._active_count - 1)

    async def cancel(self, session_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(session_id)
        if task is None: return False
        task.cancel()
        return True


class WorkflowService:
    def __init__(self, collector_manager: Any, ai_service: Any, channel_manager: Any,
                 resource_store: Any | None = None, *, max_concurrent_runs: int = 4) -> None:
        self.collector_manager = collector_manager
        self.ai_service = ai_service
        self.channel_manager = channel_manager
        self.resource_store = resource_store
        self.coordinator = RunCoordinator(max_concurrent_runs=max_concurrent_runs)
        self._shutdown = False

    async def validate(self, workflow: WorkflowDefinition | WorkflowSnapshot) -> None:
        wf = workflow.workflow if isinstance(workflow, WorkflowSnapshot) else workflow
        if not isinstance(wf, WorkflowDefinition):
            raise LogAgentError("invalid_config", "Workflow 定义无效")
        for source_id in wf.sources:
            source = workflow.sources[source_id] if isinstance(workflow, WorkflowSnapshot) else None
            if source is not None and hasattr(self.collector_manager, "validate"):
                self.collector_manager.validate(source)

    async def save(self, workflow: WorkflowDefinition, *args: Any, **kwargs: Any) -> Any:
        if self.resource_store is None or not hasattr(self.resource_store, "save"):
            return workflow
        return await _maybe_call(self.resource_store.save, "workflows", workflow, *args, **kwargs)

    async def trigger(self, workflow: str | WorkflowSnapshot | WorkflowDefinition, *, session_id: str | None = None,
                      context: CollectionContext | None = None) -> WorkflowResult:
        if self._shutdown: raise LogAgentError("shutdown", "Workflow 服务已关闭")
        snap = await self._snapshot(workflow)
        sid = session_id or uuid.uuid4().hex[:20]
        await self.coordinator.acquire(sid)
        try:
            ctx = context or CollectionContext(workflow_id=snap.workflow.id, session_id=sid)
            return await self._run_graph(snap, sid, ctx)
        except asyncio.CancelledError:
            raise
        finally:
            await self.coordinator.release(sid)

    async def cancel(self, session_id: str) -> bool: return await self.coordinator.cancel(session_id)
    async def shutdown(self) -> None:
        self._shutdown = True
        async with self.coordinator._lock:
            tasks = list(self.coordinator._tasks.values())
        for task in tasks: task.cancel()

    async def _snapshot(self, value: str | WorkflowSnapshot | WorkflowDefinition) -> WorkflowSnapshot:
        if isinstance(value, WorkflowSnapshot): return WorkflowSnapshot.model_validate(deepcopy(value.model_dump(mode="python")))
        if isinstance(value, str):
            if self.resource_store is None or not hasattr(self.resource_store, "snapshot"):
                raise LogAgentError("not_found", "Workflow 快照不存在")
            snap = await _maybe_call(self.resource_store.snapshot, value)
            return WorkflowSnapshot.model_validate(snap)
        # Resource stores commonly expose snapshot by id; use it when available.
        if self.resource_store is not None and hasattr(self.resource_store, "snapshot"):
            try:
                snap = await _maybe_call(self.resource_store.snapshot, value.id)
                return WorkflowSnapshot.model_validate(snap)
            except Exception:
                pass
        raise LogAgentError("invalid_config", "触发必须使用已保存 Workflow 快照")

    def _graph(self):
        graph = StateGraph(_State)
        graph.add_node("collect", self._collect)
        graph.add_node("analyze", self._analyze)
        graph.add_node("aggregate", self._aggregate)
        graph.add_node("notify", self._notify)
        graph.add_node("finish", self._finish)
        graph.add_edge(START, "collect")
        graph.add_conditional_edges("collect", lambda s: "finish" if s.get("stopped") else "analyze", {"finish":"finish", "analyze":"analyze"})
        graph.add_conditional_edges("analyze", lambda s: "finish" if s.get("stopped") else "aggregate", {"finish":"finish", "aggregate":"aggregate"})
        graph.add_conditional_edges("aggregate", lambda s: "finish" if s.get("stopped") else "notify", {"finish":"finish", "notify":"notify"})
        graph.add_edge("notify", "finish"); graph.add_edge("finish", END)
        return graph.compile()

    async def _run_graph(self, snap: WorkflowSnapshot, sid: str, ctx: CollectionContext) -> WorkflowResult:
        result = WorkflowResult(session_id=sid, workflow_id=snap.workflow.id)
        logger.info("workflow started", extra={"workflow_id": snap.workflow.id, "session_id": sid, "stage": "collect"})
        state: _State = {"snapshot": snap, "session_id": sid, "context": ctx, "result": result,
                         "analysis_map": {}, "outputs": {}}
        try:
            out = await self._graph().ainvoke(state)
            return out["result"]
        except asyncio.CancelledError:
            result.cancelled = True; result.stopped = True; result.stage = "finish"
            logger.info("workflow cancelled", extra={"workflow_id": snap.workflow.id, "session_id": sid, "stage": "finish"})
            return result
        finally:
            logger.info("workflow finished", extra={"workflow_id": snap.workflow.id, "session_id": sid, "stage": "finish"})

    async def _collect(self, s: _State) -> dict[str, Any]:
        snap, wf, result = s["snapshot"], s["snapshot"].workflow, s["result"]
        result.stage = "collect"
        sem = asyncio.Semaphore(wf.collection_concurrency)
        async def one(i: int, sid: str) -> tuple[int, CollectionResult]:
            async with sem:
                try:
                    value = await _maybe_call(self.collector_manager.collect, snap.sources[sid], s["context"])
                    return i, value if isinstance(value, CollectionResult) else CollectionResult.model_validate(value)
                except asyncio.CancelledError: raise
                except Exception as exc:
                    return i, CollectionResult(source_id=sid, status="failed", error=_error(exc, "collection_failed", "来源执行失败"))
        pairs = await asyncio.gather(*(one(i, sid) for i, sid in enumerate(wf.sources)))
        pairs.sort(key=lambda x: x[0]); result.collection = [p[1] for p in pairs]
        valid = [r.text for r in result.collection if r.status == "success" and r.text.strip()]
        for r in result.collection:
            policy_name = "error" if r.status in {"failed", "timeout"} else r.status
            policy = getattr(wf, f"on_{policy_name}", "notice") if r.status in {"missing", "failed", "timeout", "empty", "filtered_empty"} else "notice"
            if policy == "stop": s["stopped"] = True; result.stopped = True
        if not valid:
            if wf.on_all_empty == "stop": s["stopped"] = True; result.stopped = True
            else: s["stopped"] = True
        shared = wf.input_separator.join(valid)
        if wf.include_counts and valid:
            counts = [f"{r.source_id}: {r.status} ({r.count})" for r in result.collection]
            shared += "\n\n" + "\n".join(counts)
        s["shared_input"] = shared
        return s

    async def _analyze(self, s: _State) -> dict[str, Any]:
        snap, wf, result = s["snapshot"], s["snapshot"].workflow, s["result"]
        result.stage = "analyze"
        sem = asyncio.Semaphore(wf.analysis_concurrency)
        async def one(task: Any) -> AnalysisResult:
            async with sem:
                try:
                    cfg = snap.ai[task.ai]
                    started = time.perf_counter()
                    call = _maybe_call(self.ai_service.execute, cfg, task.prompt, s.get("shared_input", ""))
                    value = await asyncio.wait_for(call, timeout=cfg.timeout)
                    if isinstance(value, AnalysisResult):
                        return value if value.task_id == task.id else value.model_copy(update={"task_id": task.id})
                    data = dict(value)
                    data.setdefault("task_id", task.id)
                    if "elapsed_ms" not in data: data["elapsed_ms"] = (time.perf_counter() - started) * 1000
                    return AnalysisResult.model_validate(data)
                except asyncio.CancelledError: raise
                except TimeoutError:
                    return AnalysisResult(
                        task_id=task.id,
                        status="timeout",
                        error=ErrorInfo(code="analysis_timeout", message="分析任务执行超时"),
                    )
                except Exception as exc:
                    return AnalysisResult(task_id=task.id, status="failed", error=_error(exc, "analysis_failed", "分析任务执行失败"))
        vals = await asyncio.gather(*(one(t) for t in wf.analyses))
        result.analyses = vals
        s["analysis_map"] = {r.task_id: r for r in vals}
        failed = [r for r in vals if r.status != "success"]
        if failed and wf.analysis_failure == "stop": s["stopped"] = True; result.stopped = True
        if not any(r.status == "success" for r in vals): s["stopped"] = True; result.stopped = True
        if failed and not wf.send_partial: s["stopped"] = True; result.stopped = True
        return s

    async def _aggregate(self, s: _State) -> dict[str, Any]:
        snap, wf, result = s["snapshot"], s["snapshot"].workflow, s["result"]
        result.stage = "aggregate"
        amap = s.get("analysis_map", {})
        successful = {k: v for k, v in amap.items() if v.status == "success"}
        if not successful:
            s["stopped"] = True; result.stopped = True; return s
        if wf.fan_in is None:
            outputs = {k: v.text for k, v in successful.items()}
        else:
            order = wf.fan_in.order or [t.id for t in wf.analyses]
            chunks: list[str] = []
            for key in order:
                if key == "$input": chunks.append(s.get("shared_input", "")); continue
                item = amap.get(key)
                if item is None or item.status != "success":
                    if wf.fan_in.mark_incomplete: chunks.append(f"[{key}: incomplete]")
                else: chunks.append(item.text)
            joined = wf.fan_in.separator.join(x for x in chunks if x)
            if wf.fan_in.ai is None:
                outputs = {"final": joined}
            else:
                try:
                    cfg = snap.ai[wf.fan_in.ai]
                    value = await asyncio.wait_for(
                        _maybe_call(self.ai_service.execute, cfg, wf.fan_in.prompt, joined),
                        timeout=cfg.timeout,
                    )
                    if isinstance(value, AnalysisResult):
                        if value.status != "success": raise RuntimeError("aggregation failed")
                        outputs = {"final": value.text}
                    else:
                        data = dict(value)
                        outputs = {"final": AnalysisResult.model_validate({"task_id":"final", **data}).text}
                except Exception as exc:
                    result.errors.append(_error(exc, "aggregation_failed", "汇总任务执行失败"))
                    s["stopped"] = True; result.stopped = True; return s
        s["outputs"] = outputs; result.outputs = outputs
        return s

    async def _notify(self, s: _State) -> dict[str, Any]:
        snap, wf, result = s["snapshot"], s["snapshot"].workflow, s["result"]
        result.stage = "notify"
        outputs = s.get("outputs", {})
        notifications = [Notification(session_id=s["session_id"], output_id=oid, text=text,
                                       title=wf.name or wf.id) for oid, text in outputs.items()]
        result.notifications = notifications
        for note in notifications:
            for cid in wf.channels:
                cfg = snap.channels[cid]
                if not cfg.enabled:
                    result.deliveries.append(DeliveryResult(channel_id=cid, output_id=note.output_id, status="skipped", attempts=0)); continue
                try:
                    value = await asyncio.wait_for(
                        _maybe_call(self.channel_manager.send, cfg, note), timeout=cfg.timeout
                    )
                    if isinstance(value, DeliveryResult):
                        result.deliveries.append(value)
                    else:
                        data = dict(value) if isinstance(value, dict) else {}
                        data.setdefault("channel_id", cid); data.setdefault("output_id", note.output_id)
                        data.setdefault("status", "success"); data.setdefault("attempts", 1)
                        result.deliveries.append(DeliveryResult.model_validate(data))
                except TimeoutError:
                    result.deliveries.append(DeliveryResult(channel_id=cid, output_id=note.output_id, status="timeout", attempts=1,
                                                          error=ErrorInfo(code="delivery_timeout", message="通知发送超时")))
                except asyncio.CancelledError: raise
                except Exception as exc:
                    result.deliveries.append(DeliveryResult(channel_id=cid, output_id=note.output_id, status="failed", attempts=1,
                                                          error=_error(exc, "delivery_failed", "通知发送失败")))
        return s

    async def _finish(self, s: _State) -> dict[str, Any]:
        s["result"].stage = "finish"
        if s.get("cancelled"): s["result"].cancelled = True
        return s
