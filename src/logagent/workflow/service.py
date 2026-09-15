"""Durable LangGraph workflows with SQLite stage history and delivery receipts."""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import Field, TypeAdapter

from logagent.errors import LogAgentError, exception_error
from logagent.models import (
    ID,
    AnalysisResult,
    CollectionContext,
    CollectionResult,
    DeliveryResult,
    ErrorInfo,
    ExecutionContext,
    Notification,
    StrictModel,
    WorkflowDefinition,
    WorkflowSnapshot,
    copy_model,
)
from logagent.workflow.store import SQLiteRunStore

logger = logging.getLogger("logagent.workflow")
_STAGES = ("collect", "analyze", "aggregate", "notify", "finish")
_ID = TypeAdapter(ID)


class WorkflowResult(StrictModel):
    session_id: ID
    workflow_id: ID
    stage: Literal["collect", "analyze", "aggregate", "notify", "finish"] = "collect"
    status: Literal["running", "completed", "partial", "failed", "cancelled", "interrupted"] = (
        "running"
    )
    collection: list[CollectionResult] = Field(default_factory=list)
    shared_input: str = ""
    analyses: list[AnalysisResult] = Field(default_factory=list)
    aggregate: AnalysisResult | None = None
    outputs: dict[str, str] = Field(default_factory=dict)
    notifications: list[Notification] = Field(default_factory=list)
    deliveries: list[DeliveryResult] = Field(default_factory=list)
    stopped: bool = False
    cancelled: bool = False
    errors: list[ErrorInfo] = Field(default_factory=list)

    @property
    def collection_results(self) -> list[CollectionResult]:
        return self.collection

    @property
    def analysis_results(self) -> list[AnalysisResult]:
        return self.analyses


class _State(TypedDict):
    # Only JSON data reaches LangGraph serialization. Clients, resolvers and
    # CollectionContext are bound to node closures for this invocation.
    session_id: str
    result: dict[str, Any]


class _Halted(Exception):
    def __init__(self, result: WorkflowResult):
        self.result = result
        # No provider text, prompts, or result bodies in graph error writes.
        super().__init__("Workflow stopped by failure policy")


async def _call(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    value = fn(*args, **kwargs)
    return await value if inspect.isawaitable(value) else value


class RunCoordinator:
    def __init__(self, *, max_concurrent_runs: int = 4) -> None:
        if type(max_concurrent_runs) is not int or max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be a positive integer")
        self._max = max_concurrent_runs
        self._tasks: dict[str, asyncio.Task] = {}

    @property
    def active(self) -> int:
        return len(self._tasks)

    async def acquire(self, session_id: str) -> None:
        # No await between checking and claiming: atomic within an event loop.
        if session_id in self._tasks:
            raise LogAgentError("session_active", "同一 session 已在运行")
        if self.active >= self._max:
            raise LogAgentError("capacity_exhausted", "运行容量已满")
        self._tasks[session_id] = asyncio.current_task()

    async def release(self, session_id: str) -> None:
        self._tasks.pop(session_id, None)

    async def cancel(self, session_id: str) -> bool:
        task = self._tasks.get(session_id)
        if task is None:
            return False
        task.cancel()
        return True

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class WorkflowService:
    def __init__(
        self,
        collector_manager: Any,
        ai_service: Any,
        channel_manager: Any,
        resource_store: Any | None = None,
        *,
        run_store: SQLiteRunStore | None = None,
        database: str | Path | None = None,
        max_concurrent_runs: int = 4,
        credentials: Any = None,
    ) -> None:
        self.collector_manager = collector_manager
        self.ai_service = ai_service
        self.channel_manager = channel_manager
        self.resource_store = resource_store
        self.credentials = credentials
        location = database if database is not None else getattr(resource_store, "location", None)
        if location is None or (database is None and str(location) == ":memory:"):
            location = "data/workflows.sqlite3"
        if str(run_store.location if run_store is not None else location) in {"", ":memory:"}:
            raise LogAgentError("invalid_argument", "可恢复 Workflow 必须使用 SQLite 文件")
        self.run_store = run_store if run_store is not None else SQLiteRunStore(location)
        self._owns_store = run_store is None
        self.coordinator = RunCoordinator(max_concurrent_runs=max_concurrent_runs)
        self._shutdown = False
        self._live: dict[str, WorkflowResult] = {}

    async def _db(self, method: str, *args: Any, **kwargs: Any) -> Any:
        # SQLite calls run off the event loop. A cancelled write must settle before
        # its session claim is released, otherwise recovery can race the commit.
        task = asyncio.create_task(
            asyncio.to_thread(getattr(self.run_store, method), *args, **kwargs)
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
            task.result()
            raise

    async def validate(self, workflow: WorkflowDefinition | WorkflowSnapshot) -> None:
        if isinstance(workflow, WorkflowSnapshot):
            snap = copy_model(workflow)
            for source in snap.sources.values():
                self.collector_manager.validate(source)
            for config in snap.ai.values():
                self.ai_service.validate(config)
            for channel in snap.channels.values():
                self.channel_manager.validate(channel)
        else:
            copy_model(workflow)

    async def save(self, workflow: WorkflowDefinition, **kwargs: Any) -> Any:
        if self.resource_store is None:
            raise LogAgentError("configuration_unavailable", "未注入资源仓库")
        return await _call(self.resource_store.save, "workflows", copy_model(workflow), **kwargs)

    async def _snapshot(
        self, workflow: str | WorkflowSnapshot | WorkflowDefinition
    ) -> WorkflowSnapshot:
        if isinstance(workflow, WorkflowSnapshot):
            return copy_model(workflow)
        if self.resource_store is None:
            raise LogAgentError("configuration_unavailable", "未注入资源仓库")
        ident = workflow.id if isinstance(workflow, WorkflowDefinition) else workflow
        value = await _call(self.resource_store.snapshot, ident)
        return copy_model(value)

    def _context(
        self,
        snapshot: WorkflowSnapshot,
        sid: str,
        context: CollectionContext | None,
        saved: dict[str, Any] | None = None,
    ) -> CollectionContext:
        if context is not None:
            if context.workflow_id != snapshot.workflow.id or context.session_id != sid:
                raise LogAgentError("invalid_argument", "上下文与 session 不匹配")
            if saved is not None and context.log_path != saved.get("log_path"):
                raise LogAgentError("invalid_argument", "恢复不能修改既有日志来源路径")
            return context
        return CollectionContext(
            snapshot.workflow.id, sid, (saved or {}).get("log_path"), self.credentials
        )

    async def _admit(self, sid: str) -> None:
        if self._shutdown:
            raise LogAgentError("shutdown", "Workflow 服务已关闭")
        _ID.validate_python(sid)
        await self.coordinator.acquire(sid)
        try:
            # Process-wide claim also prevents two service objects replaying a
            # single session concurrently. Multi-process writers are not supported.
            if not self.run_store.claim(sid):
                raise LogAgentError("session_active", "同一 session 已在运行")
        except BaseException:
            await self.coordinator.release(sid)
            raise

    async def _release(self, sid: str) -> None:
        self._live.pop(sid, None)
        self.run_store.release(sid)
        await self.coordinator.release(sid)

    async def trigger(
        self,
        workflow: str | WorkflowSnapshot | WorkflowDefinition,
        *,
        session_id: str | None = None,
        context: CollectionContext | None = None,
    ) -> WorkflowResult:
        sid = session_id or uuid.uuid4().hex
        await self._admit(sid)
        try:
            snapshot = await self._snapshot(workflow)
            if not snapshot.workflow.enabled:
                raise LogAgentError("workflow_disabled", "Workflow 已禁用")
            ctx = self._context(snapshot, sid, context)
            await self._db("create_session", sid, snapshot, {"log_path": ctx.log_path})
            return await self._execute(snapshot, sid, ctx, resume=False)
        finally:
            await self._release(sid)

    async def recover(
        self, session_id: str, *, context: CollectionContext | None = None
    ) -> WorkflowResult:
        await self._admit(session_id)
        try:
            await self._db("verify_session", session_id)
            record = await self._db("get_session", session_id)
            if record is None:
                raise LogAgentError("session_not_found", "Workflow session 不存在")
            # All finished notification receipts (including uncertain ones) remain
            # final. Retry analysis after frozen output requires a new session.
            final = await self._db("stage_result", session_id, "finish")
            if final is not None:
                result = WorkflowResult.model_validate(final)
                if record["status"] != result.status:
                    await self._db("set_status", session_id, result.status)
                return result
            snapshot = WorkflowSnapshot.model_validate(record["snapshot"])
            ctx = self._context(snapshot, session_id, context, record["context"])
            await self._db("append_history", session_id, record["stage"], "resumed", {})
            return await self._execute(snapshot, session_id, ctx, resume=True)
        finally:
            await self._release(session_id)

    resume = recover

    async def get_session(self, session_id: str) -> dict[str, Any]:
        await self._db("verify_session", session_id)
        record = await self._db("get_session", session_id)
        if record is None:
            raise LogAgentError("session_not_found", "Workflow session 不存在")
        record["active"] = session_id in self.coordinator._tasks
        record["stages"] = {
            stage: await self._db("stage_result", session_id, stage) for stage in _STAGES
        }
        record["recoverable"] = record["stages"]["finish"] is None
        record["result"] = record["stages"]["finish"]
        record["collections"] = await self._db("item_results", session_id, "collect")
        record["analyses"] = await self._db("item_results", session_id, "analyze")
        record["deliveries"] = await self._db("delivery_results", session_id)
        return record

    async def list_sessions(
        self, workflow_id: str | None = None, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        return await self._db("list_sessions", workflow_id, limit=limit, offset=offset)

    async def history(
        self, session_id: str, *, stage: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        return await self._db("history", session_id, stage=stage, limit=limit, offset=offset)

    async def cancel(self, session_id: str) -> bool:
        return await self.coordinator.cancel(session_id)

    async def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        await self.coordinator.shutdown()
        if self._owns_store:
            await self._db("close")

    def _graph(self, snapshot: WorkflowSnapshot, ctx: CollectionContext, checkpointer: Any):
        graph = StateGraph(_State)
        for stage in _STAGES:

            async def node(state: _State, stage: str = stage) -> dict[str, Any]:
                return await self._stage(stage, state, snapshot, ctx)

            graph.add_node(stage, node)
        graph.add_edge(START, "collect")
        for index, stage in enumerate(_STAGES[:-2]):
            next_stage = _STAGES[index + 1]
            graph.add_conditional_edges(
                stage,
                lambda state, next_stage=next_stage: (
                    "finish" if state["result"]["stopped"] else next_stage
                ),
                {"finish": "finish", next_stage: next_stage},
            )
        graph.add_edge("notify", "finish")
        graph.add_edge("finish", END)
        return graph.compile(checkpointer=checkpointer)

    async def _execute(
        self, snapshot: WorkflowSnapshot, sid: str, ctx: CollectionContext, *, resume: bool
    ) -> WorkflowResult:
        result = WorkflowResult(session_id=sid, workflow_id=snapshot.workflow.id)
        self._live[sid] = result
        config = {"configurable": {"thread_id": sid}}
        try:
            await self._db("set_status", sid, "running")
            async with AsyncSqliteSaver.from_conn_string(self.run_store.location) as saver:
                graph = self._graph(snapshot, ctx, saver)
                checkpoint = await graph.aget_state(config) if resume else None
                if (
                    checkpoint
                    and checkpoint.values
                    and not checkpoint.next
                    and not checkpoint.tasks
                ):
                    # END is only trustworthy when the corresponding durable
                    # business result exists; never reconstruct missing facts.
                    raise LogAgentError("storage_corrupt", "已结束的图缺少最终阶段记录")
                state = (
                    None
                    if checkpoint and checkpoint.values
                    else {"session_id": sid, "result": result.model_dump(mode="json")}
                )
                out = await graph.ainvoke(state, config=config)
                return WorkflowResult.model_validate(out["result"])
        except _Halted as exc:
            await self._db("set_status", sid, "failed", error=exc.result.errors[-1])
            return exc.result
        except asyncio.CancelledError:
            result = self._live[sid]
            result.status = "cancelled"
            result.cancelled = True
            await self._db(
                "append_history", sid, result.stage, "cancelled", result.model_dump(mode="json")
            )
            await self._db("set_status", sid, "cancelled")
            return result
        except Exception as exc:
            # Stage wrappers redact service errors; failures here are checkpoint
            # infrastructure failures. Never start a later external operation.
            try:
                await self._db(
                    "set_status",
                    sid,
                    "interrupted",
                    error=ErrorInfo(
                        code="checkpoint_failed", message="运行存储或 checkpoint 写入失败"
                    ),
                )
            except Exception:
                logger.error(
                    "Unable to persist interrupted workflow status", extra={"session_id": sid}
                )
            if isinstance(exc, LogAgentError):
                raise
            raise LogAgentError("checkpoint_failed", "运行存储或 checkpoint 写入失败") from None

    async def _stage(
        self, stage: str, state: _State, snapshot: WorkflowSnapshot, ctx: CollectionContext
    ) -> dict[str, Any]:
        sid = state["session_id"]
        incoming = WorkflowResult.model_validate(state["result"])
        if incoming.session_id != sid or incoming.workflow_id != snapshot.workflow.id:
            raise LogAgentError("storage_corrupt", "Checkpoint 的运行标识不匹配")
        if stage != "collect":
            previous = (
                "collect"
                if stage == "finish" and incoming.stopped
                else _STAGES[_STAGES.index(stage) - 1]
            )
            prerequisite = await self._db("stage_result", sid, previous)
            if prerequisite is None or prerequisite != incoming.model_dump(mode="json"):
                raise LogAgentError("storage_corrupt", "Checkpoint 缺少匹配的前序阶段记录")
        saved = await self._db("stage_result", sid, stage)
        if saved is not None:
            result = WorkflowResult.model_validate(saved)
            self._live[sid] = result
            return {"result": result.model_dump(mode="json")}
        result = incoming
        result.stage, result.status = stage, "running"
        result.cancelled = False
        self._live[sid] = result
        await self._db("append_history", sid, stage, "started", result.model_dump(mode="json"))
        logger.info(
            "workflow stage",
            extra={"session_id": sid, "workflow_id": snapshot.workflow.id, "stage": stage},
        )
        await getattr(self, "_" + stage)(result, snapshot, ctx)
        if stage != "finish" and result.status == "failed":
            await self._db("append_history", sid, stage, "failed", result.model_dump(mode="json"))
            raise _Halted(result)
        # The stage journal commits before graph advancement. If graph checkpoint
        # persistence fails, replay returns this exact result without repeating I/O.
        await self._db("save_stage", sid, stage, result.model_dump(mode="json"))
        if stage == "finish":
            await self._db("set_status", sid, result.status)
        return {"result": result.model_dump(mode="json")}

    @staticmethod
    def _halt(result: WorkflowResult, code: str, message: str) -> None:
        result.stopped, result.status = True, "failed"
        result.errors.append(ErrorInfo(code=code, message=message))

    async def _collect(
        self, result: WorkflowResult, snapshot: WorkflowSnapshot, ctx: CollectionContext
    ) -> None:
        wf, sid = snapshot.workflow, result.session_id
        records = await self._db("item_results", sid, "collect")
        sem = asyncio.Semaphore(wf.collection_concurrency)

        async def one(source_id: str) -> None:
            async with sem:
                if records.get(source_id, {}).get("status") in {
                    "success",
                    "empty",
                    "filtered_empty",
                }:
                    return
                await self._db(
                    "append_history", sid, "collect", "item_started", {"source_id": source_id}
                )
                try:
                    config = copy_model(snapshot.sources[source_id])
                    async with asyncio.timeout(config.timeout):
                        raw = await self.collector_manager.collect(config, ctx)
                    output = (
                        copy_model(raw)
                        if isinstance(raw, CollectionResult)
                        else CollectionResult.model_validate(raw)
                    )
                    if output.source_id != source_id:
                        raise ValueError("Collector source identity mismatch")
                except TimeoutError:
                    output = CollectionResult(
                        source_id=source_id,
                        status="timeout",
                        error=ErrorInfo(code="collection_timeout", message="来源采集超时"),
                    )
                except Exception as exc:
                    output = CollectionResult(
                        source_id=source_id,
                        status="failed",
                        error=exception_error(
                            exc, code="collection_failed", message="来源采集失败"
                        ),
                    )
                records[source_id] = output.model_dump(mode="json")
                await self._db("save_item", sid, "collect", source_id, records[source_id])

        await self._parallel(one, wf.sources)
        result.collection = [CollectionResult.model_validate(records[key]) for key in wf.sources]
        valid = [item.text for item in result.collection if item.status == "success"]
        result.shared_input = wf.input_separator.join(valid)
        if wf.include_counts and valid:
            result.shared_input += "\n\n" + "\n".join(
                f"{item.source_id}: {item.status} ({item.count})" for item in result.collection
            )
        for item in result.collection:
            if item.status == "success":
                continue
            policy = "error" if item.status in {"failed", "timeout"} else item.status
            if getattr(snapshot.sources[item.source_id], "on_" + policy) == "stop":
                self._halt(result, "collection_stopped", "来源策略要求停止下游阶段")
                return
        if not valid:
            if wf.on_all_empty == "stop":
                self._halt(result, "all_empty", "所有来源均无有效内容")
            else:
                result.stopped = True

    @staticmethod
    async def _parallel(call: Callable, values: list[Any]) -> None:
        tasks = [asyncio.create_task(call(value)) for value in values]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _analysis_call(
        self, config: Any, prompt: str, text: str, task_id: str, result: WorkflowResult
    ) -> AnalysisResult:
        try:
            async with asyncio.timeout(config.timeout):
                raw = await self.ai_service.execute(
                    copy_model(config),
                    prompt,
                    text,
                    task_id=task_id,
                    context=ExecutionContext(
                        workflow_id=result.workflow_id,
                        session_id=result.session_id,
                        stage=result.stage,
                    ),
                )
            # AIService may translate caller cancellation into a result. Preserve
            # the caller signal so no queued analysis or notification starts.
            if asyncio.current_task().cancelling():
                raise asyncio.CancelledError
            output = (
                copy_model(raw)
                if isinstance(raw, AnalysisResult)
                else AnalysisResult.model_validate(raw)
            )
            if output.task_id != task_id:
                raise ValueError("Analysis task identity mismatch")
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

    async def _analyze(
        self, result: WorkflowResult, snapshot: WorkflowSnapshot, ctx: CollectionContext
    ) -> None:
        wf, sid = snapshot.workflow, result.session_id
        records = await self._db("item_results", sid, "analyze")
        sem = asyncio.Semaphore(wf.analysis_concurrency)

        async def one(task: Any) -> None:
            async with sem:
                if records.get(task.id, {}).get("status") == "success":
                    return
                await self._db(
                    "append_history", sid, "analyze", "item_started", {"task_id": task.id}
                )
                output = await self._analysis_call(
                    snapshot.ai[task.ai], task.prompt, result.shared_input, task.id, result
                )
                records[task.id] = output.model_dump(mode="json")
                await self._db("save_item", sid, "analyze", task.id, records[task.id])

        await self._parallel(one, wf.analyses)
        result.analyses = [AnalysisResult.model_validate(records[task.id]) for task in wf.analyses]
        failed = [item for item in result.analyses if item.status != "success"]
        if len(failed) == len(result.analyses) or (
            failed and (wf.analysis_failure == "stop" or not wf.send_partial)
        ):
            self._halt(result, "analysis_stopped", "分析失败策略阻止下游阶段")

    async def _aggregate(
        self, result: WorkflowResult, snapshot: WorkflowSnapshot, ctx: CollectionContext
    ) -> None:
        wf = snapshot.workflow
        if wf.fan_in is None:
            result.outputs = {
                item.task_id: item.text for item in result.analyses if item.status == "success"
            }
        else:
            by_id = {item.task_id: item for item in result.analyses}
            parts: list[str] = []
            for key in wf.fan_in.order or [item.id for item in wf.analyses]:
                if key == "$input":
                    parts.append(result.shared_input)
                elif by_id[key].status == "success":
                    parts.append(by_id[key].text)
                elif wf.fan_in.mark_incomplete:
                    parts.append(f"[{key}: incomplete]")
            text = wf.fan_in.separator.join(parts)
            if not text.strip():
                self._halt(result, "aggregate_empty", "汇总未产生有效正文")
                return
            if wf.fan_in.ai:
                records = await self._db("item_results", result.session_id, "aggregate")
                previous = records.get("final")
                if previous and previous["status"] == "success":
                    result.aggregate = AnalysisResult.model_validate(previous)
                else:
                    await self._db(
                        "append_history", result.session_id, "aggregate", "input", {"text": text}
                    )
                    result.aggregate = await self._analysis_call(
                        snapshot.ai[wf.fan_in.ai], wf.fan_in.prompt, text, "final", result
                    )
                    await self._db(
                        "save_item",
                        result.session_id,
                        "aggregate",
                        "final",
                        result.aggregate.model_dump(mode="json"),
                    )
                if result.aggregate.status != "success":
                    self._halt(result, "aggregate_failed", "AI 汇总失败")
                    return
                text = result.aggregate.text
            result.outputs = {"final": text}
        # Output is frozen by the aggregate stage transaction, before any send.
        result.notifications = [
            Notification(
                session_id=result.session_id, output_id=key, title=wf.name or wf.id, text=text
            )
            for key, text in result.outputs.items()
        ]

    @staticmethod
    def _uncertain(channel_id: str, output_id: str) -> DeliveryResult:
        return DeliveryResult(
            channel_id=channel_id,
            output_id=output_id,
            status="failed",
            attempts=1,
            error=ErrorInfo(
                code="delivery_uncertain",
                message="既有发送未获得可靠回执，不自动补发",
                details={"delivery_uncertain": True},
            ),
        )

    async def _notify(
        self, result: WorkflowResult, snapshot: WorkflowSnapshot, ctx: CollectionContext
    ) -> None:
        sid = result.session_id
        previous = {
            (row["output_id"], row["channel_id"]): row
            for row in await self._db("delivery_results", sid)
        }
        result.deliveries = []
        for note in result.notifications:
            for cid in snapshot.workflow.channels:
                key = (note.output_id, cid)
                if key in previous:
                    receipt = DeliveryResult.model_validate(previous[key])
                    await self._db("save_delivery", sid, receipt.model_dump(mode="json"))
                    result.deliveries.append(receipt)
                    continue
                config = snapshot.channels[cid]
                claimed = await self._db("begin_delivery", sid, note.output_id, cid)
                if not claimed:
                    receipt = self._uncertain(cid, note.output_id)
                elif not config.enabled:
                    receipt = DeliveryResult(
                        channel_id=cid, output_id=note.output_id, status="skipped", attempts=0
                    )
                else:
                    try:
                        async with asyncio.timeout(config.timeout):
                            raw = await self.channel_manager.send(
                                copy_model(config), copy_model(note)
                            )
                        receipt = (
                            copy_model(raw)
                            if isinstance(raw, DeliveryResult)
                            else DeliveryResult.model_validate(raw)
                        )
                        if receipt.channel_id != cid or receipt.output_id != note.output_id:
                            raise ValueError("Delivery identity mismatch")
                        if (receipt.status in {"success", "skipped"}) != (receipt.error is None):
                            raise ValueError("Invalid delivery result")
                    except asyncio.CancelledError:
                        receipt = self._uncertain(cid, note.output_id)
                        await self._db("save_delivery", sid, receipt.model_dump(mode="json"))
                        result.deliveries.append(receipt)
                        raise
                    except TimeoutError:
                        receipt = self._uncertain(cid, note.output_id)
                        receipt.status = "timeout"
                    except Exception:
                        receipt = self._uncertain(cid, note.output_id)
                await self._db("save_delivery", sid, receipt.model_dump(mode="json"))
                result.deliveries.append(receipt)

    async def _finish(
        self, result: WorkflowResult, snapshot: WorkflowSnapshot, ctx: CollectionContext
    ) -> None:
        degraded = any(
            item.status in {"failed", "missing", "timeout"} for item in result.collection
        )
        degraded |= any(item.status != "success" for item in result.analyses)
        degraded |= any(item.status in {"failed", "timeout"} for item in result.deliveries)
        result.status = "partial" if degraded else "completed"
