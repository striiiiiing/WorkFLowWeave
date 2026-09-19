"""LangGraph execution with idempotent, independently readable business archives."""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal, TypedDict

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
from logagent.workflow.nodes import ArchiveRuntime, archive_node
from logagent.workflow.session_store import SessionStore
from logagent.workflow.session_view import SessionView

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
    def collection_results(self):
        return self.collection

    @property
    def analysis_results(self):
        return self.analyses


def _merge(left, right):
    return {**left, **right}


class _State(TypedDict):
    session_id: str
    phases: Annotated[dict[str, str], _merge]
    stopped: bool
    status: str
    generation: int
    retry_stage: str | None


class _ChildState(_State):
    items: Annotated[dict[str, str], _merge]


async def _call(fn: Callable, *args, **kwargs):
    value = fn(*args, **kwargs)
    return await value if inspect.isawaitable(value) else value


def _safe_node(operation):
    async def node(state):
        try:
            return await operation(state)
        except LogAgentError:
            raise
        except Exception as exc:
            error = exception_error(
                exc, code="workflow_failed", message="Workflow 节点执行或存档失败"
            )
            raise LogAgentError(error.code, error.message, error.details) from None

    return node


def _archive_references(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"items", "phases"} and isinstance(child, dict):
                yield from (ref for ref in child.values() if isinstance(ref, str) and ref)
            else:
                yield from _archive_references(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _archive_references(child)


class RunCoordinator:
    # Retain a small, explicit wait window, including errors. Business history lives
    # in SessionStore; completed tasks must not accumulate for the service lifetime.
    COMPLETED_LIMIT = 32

    def __init__(self, *, max_concurrent_runs=4):
        if type(max_concurrent_runs) is not int or max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be positive")
        self._max = max_concurrent_runs
        self._tasks: dict[str, asyncio.Task] = {}
        self._completed: OrderedDict[str, asyncio.Task] = OrderedDict()
        self._started: dict[str, asyncio.Event] = {}
        self.accepting = True

    @property
    def active(self):
        return len(self._tasks)

    def contains(self, sid):
        return sid in self._tasks

    def check(self, sid):
        if not self.accepting:
            raise LogAgentError("not_ready", "Workflow 未开放运行准入")
        if sid in self._tasks:
            raise LogAgentError("session_active", "同一 session 已在运行")
        if self.active >= self._max:
            raise LogAgentError("capacity_exhausted", "运行容量已满")

    def submit(self, sid, operation):
        self.check(sid)
        started = self._started[sid] = asyncio.Event()

        async def run():
            started.set()
            return await operation()

        def done(task):
            self._tasks.pop(sid, None)
            self._started.pop(sid, None)
            # Retrieve exceptions even when no HTTP client waits for this task.
            if not task.cancelled():
                task.exception()
            self._completed[sid] = task
            while len(self._completed) > self.COMPLETED_LIMIT:
                self._completed.popitem(last=False)

        self._completed.pop(sid, None)
        task = asyncio.create_task(run(), name=f"workflow:{sid}")
        self._tasks[sid] = task
        task.add_done_callback(done)

    async def wait(self, sid):
        task = self._tasks.get(sid) or self._completed.get(sid)
        if task is None:
            raise LogAgentError("session_not_active", "运行结果已离开内存等待窗口，请查询 session")
        return await asyncio.shield(task)

    async def cancel(self, sid):
        task = self._tasks.get(sid)
        if task is None or task.done():
            return False
        # A coroutine cancelled before its first instruction cannot persist a
        # cancelled event. Let its exception boundary become active first.
        await self._started[sid].wait()
        task.cancel()
        return True

    async def shutdown(self):
        self.accepting = False
        tasks = list(self._tasks.values())
        for sid in list(self._tasks):
            await self.cancel(sid)
        await asyncio.gather(*tasks, return_exceptions=True)


class WorkflowService:
    def __init__(
        self,
        collector_manager,
        ai_service,
        channel_manager,
        resource_store=None,
        *,
        session_store=None,
        session_view=None,
        checkpointer=None,
        database=None,
        max_concurrent_runs=4,
        credentials=None,
        log_path=None,
    ):
        self.collector_manager, self.ai_service = collector_manager, ai_service
        self.channel_manager, self.resource_store = channel_manager, resource_store
        self.credentials, self.log_path = credentials, log_path
        location = Path(database or "data/workflows.sqlite3")
        if str(location) == ":memory:":
            raise LogAgentError("invalid_argument", "可恢复 Workflow 必须使用持久化文件")
        self.session_store = session_store or SessionStore(location)
        self._owns_store = session_store is None
        self.database = str(database or self.session_store.location)
        self.session_view = session_view or SessionView(self.session_store)
        self.coordinator = RunCoordinator(max_concurrent_runs=max_concurrent_runs)
        self._checkpointer, self._saver_context = checkpointer, None
        self._start_lock = asyncio.Lock()
        self._admission_lock = asyncio.Lock()
        self._shutdown = False
        self._shutdown_task: asyncio.Task | None = None

    async def start(self):
        async with self._start_lock:
            if self._shutdown:
                raise LogAgentError("shutdown", "Workflow 已关闭")
            if self._checkpointer is None:
                self._saver_context = AsyncSqliteSaver.from_conn_string(self.database)
                try:
                    self._checkpointer = await self._saver_context.__aenter__()
                    await self._checkpointer.setup()
                except BaseException:
                    await self._saver_context.__aexit__(None, None, None)
                    self._checkpointer, self._saver_context = None, None
                    raise

    async def pause_admission(self):
        """Close admission and wait until every in-flight trigger has submitted or failed."""
        async with self._admission_lock:
            self.coordinator.accepting = False
            return self.coordinator.active

    def resume_admission(self):
        if not self._shutdown:
            self.coordinator.accepting = True

    async def validate(self, workflow):
        value = copy_model(workflow)
        if isinstance(value, WorkflowSnapshot):
            for source in value.sources.values():
                self.collector_manager.validate(source)
            for config in value.ai.values():
                self.ai_service.validate(config)
            for channel in value.channels.values():
                self.channel_manager.validate(channel)

    async def save(self, workflow, **kwargs):
        if self.resource_store is None:
            raise LogAgentError("configuration_unavailable", "未注入资源仓库")
        return await _call(self.resource_store.save, "workflows", workflow, **kwargs)

    async def _snapshot(self, workflow):
        if isinstance(workflow, WorkflowSnapshot):
            return copy_model(workflow)
        if self.resource_store is None:
            raise LogAgentError("configuration_unavailable", "未注入资源仓库")
        if isinstance(workflow, WorkflowDefinition):
            raise LogAgentError(
                "invalid_argument", "触发需要已保存的 Workflow ID 或完整 WorkflowSnapshot"
            )
        return copy_model(await _call(self.resource_store.snapshot, workflow))

    async def trigger(self, workflow, *, session_id=None, context=None):
        sid = session_id or uuid.uuid4().hex
        _ID.validate_python(sid)
        await self.start()
        async with self._admission_lock:
            self.coordinator.check(sid)
            if await asyncio.to_thread(self.session_store.entry, sid, "created") is not None:
                raise LogAgentError("session_exists", "session 已存在")
            snapshot = await self._snapshot(workflow)
            if not snapshot.workflow.enabled:
                raise LogAgentError("workflow_disabled", "Workflow 已禁用")
            if context and (
                context.session_id != sid or context.workflow_id != snapshot.workflow.id
            ):
                raise LogAgentError("invalid_argument", "运行上下文与 session 不匹配")
            runtime = ArchiveRuntime(self.session_store, sid, snapshot.workflow.backup)
            await asyncio.to_thread(
                self.session_store.create, sid, snapshot.workflow.id, runtime.policy
            )
            ctx = context or CollectionContext(
                snapshot.workflow.id, sid, self.log_path, self.credentials, self.session_view
            )
            await self._snapshot_node(runtime, snapshot, ctx)({})
            self.coordinator.submit(sid, lambda: self._execute(sid, snapshot, ctx, resume=False))
        return sid

    async def recover(self, session_id, *, context=None):
        _ID.validate_python(session_id)
        await self.start()
        async with self._admission_lock:
            self.coordinator.check(session_id)
            config = {"configurable": {"thread_id": session_id}}
            checkpoint = await self._checkpointer.aget_tuple(config)
            if checkpoint is None:
                raise LogAgentError(
                    "checkpoint_missing", "缺少原 checkpoint，无法从业务存档猜测进度"
                )
            entry = await asyncio.to_thread(self.session_store.entry, session_id, "snapshot")
            if entry is None or entry["body"] is None:
                raise LogAgentError("recovery_unavailable", "原配置快照不可用")
            snapshot = WorkflowSnapshot.model_validate(entry["body"]["snapshot"])
            _, archives = await asyncio.to_thread(self.session_store.entries, session_id)
            existing = {entry["write_key"] for entry in archives}
            async for saved in self._checkpointer.alist(config):
                refs = set(_archive_references(saved.checkpoint.get("channel_values", {})))
                for _, channel, value in saved.pending_writes or []:
                    refs.update(_archive_references({channel: value}))
                missing = refs - existing
                if missing:
                    raise LogAgentError(
                        "recovery_unavailable",
                        "checkpoint 引用的业务内容缺失",
                        {"keys": sorted(missing)},
                    )
            frozen = next(
                (
                    e
                    for e in reversed(archives)
                    if e["scope"] == "phase"
                    and e["stage"] == "aggregate"
                    and not e["summary"].get("stopped")
                ),
                None,
            )
            needed = (
                [frozen]
                if frozen
                else [e for e in archives if e["category"] in {"collection", "analysis"}]
            )
            unavailable = [e for e in needed if e["availability"] != "available"]
            if unavailable:
                raise LogAgentError(
                    "recovery_unavailable",
                    "恢复所需的原阶段内容不可用",
                    {
                        "content": [
                            {"key": e["write_key"], "reason": e["availability"]}
                            for e in unavailable
                        ]
                    },
                )
            saved_path = entry["body"].get("log_path")
            if context and (
                context.log_path != saved_path
                or context.session_id != session_id
                or context.workflow_id != snapshot.workflow.id
            ):
                raise LogAgentError("invalid_argument", "恢复不能替换原日志路径")
            context = context or CollectionContext(
                snapshot.workflow.id, session_id, saved_path, self.credentials, self.session_view
            )
            self.coordinator.submit(
                session_id, lambda: self._execute(session_id, snapshot, context, resume=True)
            )
        return session_id

    resume = recover

    async def wait(self, session_id):
        return await self.coordinator.wait(session_id)

    async def get_session(self, session_id, *, version=None):
        return await self.session_view.get_session(session_id, version=version)

    async def list_sessions(self, workflow_id=None, **kwargs):
        return await self.session_view.list_sessions(workflow_id, **kwargs)

    async def history(self, session_id):
        _, entries = await asyncio.to_thread(self.session_store.entries, session_id)
        return [{k: value for k, value in entry.items() if k != "digest"} for entry in entries]

    async def cancel(self, session_id):
        return await self.coordinator.cancel(session_id)

    async def reconcile_interrupted(self):
        from logagent.models import BackupPolicy

        offset = 0
        while records := await self.list_sessions(limit=1000, offset=offset):
            for record in records:
                if record.status not in {"created", "running"} or self.coordinator.contains(
                    record.session_id
                ):
                    continue
                header, _ = await asyncio.to_thread(self.session_store.entries, record.session_id)
                runtime = ArchiveRuntime(
                    self.session_store,
                    record.session_id,
                    BackupPolicy.model_validate_json(header["policy"]),
                )
                await self._event(
                    runtime, f"interrupted:{record.version}", record.stage, "interrupted"
                )
            offset += len(records)

    async def shutdown(self):
        if self._shutdown_task is None or (
            self._shutdown_task.done() and self._shutdown_task.exception() is not None
        ):
            self._shutdown_task = asyncio.create_task(self._shutdown_once())
        await asyncio.shield(self._shutdown_task)

    async def _shutdown_once(self):
        async with self._start_lock:
            await self.pause_admission()
            self._shutdown = True
        await self.coordinator.shutdown()
        if self._saver_context is not None:
            await self._saver_context.__aexit__(None, None, None)
            self._saver_context = None
        if self._owns_store:
            await asyncio.to_thread(self.session_store.close)

    async def _event(self, runtime, key, stage, status, error=None):
        async def value(state):
            return {"status": status, "error": error.model_dump(mode="json") if error else None}

        node = archive_node(
            runtime,
            scope="parent",
            stage=stage,
            key=key,
            category=None,
            operation=value,
            summarize=lambda body: body,
        )
        await node({})

    async def _result(self, runtime, snapshot, state, *, required=()):
        result = WorkflowResult(session_id=runtime.session_id, workflow_id=snapshot.workflow.id)
        for stage in _STAGES:
            key = state.get("phases", {}).get(stage)
            if not key:
                continue
            try:
                body = await runtime.read(key)
            except LogAgentError as exc:
                if stage in required or exc.code != "recovery_unavailable":
                    raise
                continue
            errors = body.pop("errors", [])
            result = WorkflowResult.model_validate(
                {
                    **result.model_dump(mode="json"),
                    **body,
                    "stage": stage,
                    "errors": errors or [e.model_dump(mode="json") for e in result.errors],
                }
            )
        return result

    async def _final_result(self, runtime, snapshot, state):
        result = await self._result(runtime, snapshot, state)
        record = await self.get_session(runtime.session_id)
        if result.status in {"completed", "partial", "failed"} and record.status != result.status:
            await self._event(runtime, f"settled:{record.version}", result.stage, result.status)
        return result

    async def _execute(self, sid, snapshot, context, *, resume):
        runtime = ArchiveRuntime(self.session_store, sid, snapshot.workflow.backup)
        ctx = context or CollectionContext(
            snapshot.workflow.id, sid, self.log_path, self.credentials, self.session_view
        )
        config = {"configurable": {"thread_id": sid}}
        graph = self._graph(runtime, snapshot, ctx)
        state = {
            "session_id": sid,
            "phases": {},
            "stopped": False,
            "status": "running",
            "generation": 0,
            "retry_stage": None,
        }
        try:
            if resume:
                saved = await graph.aget_state(config, subgraphs=True)
                state = saved.values
                if not saved.next and not saved.tasks:
                    retry_stage = state.get("retry_stage")
                    if state.get("status") != "failed" or retry_stage is None:
                        return await self._final_result(runtime, snapshot, state)
                    # The retry boundary is explicit control state in the original
                    # checkpoint, never inferred from the business archive's stage.
                    record = await self.get_session(sid)
                    clear = {stage: "" for stage in _STAGES[_STAGES.index(retry_stage) :]}
                    await graph.aupdate_state(
                        config,
                        {
                            "phases": clear,
                            "stopped": False,
                            "status": "running",
                            "retry_stage": None,
                            "generation": record.version,
                        },
                        as_node=f"start_{retry_stage}",
                    )
            record = await self.get_session(sid)
            epoch = record.version
            await self._event(runtime, f"running:{epoch}", record.stage, "running")
            state = await graph.ainvoke(None if resume else state, config, durability="sync")
            return await self._final_result(runtime, snapshot, state)
        except asyncio.CancelledError:
            saved = await graph.aget_state(config)
            state = saved.values or state
            result = await self._result(runtime, snapshot, state)
            result.status, result.cancelled = "cancelled", True
            record = await self.get_session(sid)
            await self._event(runtime, f"cancelled:{record.version}", result.stage, "cancelled")
            return result
        except Exception as exc:
            error = (
                exc.info
                if isinstance(exc, LogAgentError)
                else exception_error(exc, code="workflow_failed", message="Workflow 执行或存档失败")
            )
            try:
                record = await self.get_session(sid)
                await self._event(
                    runtime, f"failed:{record.version}", record.stage, "interrupted", error
                )
            except Exception:
                logger.exception("Unable to persist interrupted session", extra={"session_id": sid})
            raise LogAgentError(error.code, error.message, error.details) from None

    def _snapshot_node(self, runtime, snapshot, ctx):
        async def body(_):
            return {"snapshot": snapshot.model_dump(mode="json"), "log_path": ctx.log_path}

        return archive_node(
            runtime,
            scope="parent",
            stage=None,
            key="snapshot",
            category="snapshot",
            operation=body,
            summarize=lambda _: {"status": "created"},
            publish=lambda key, summary: {},
        )

    def _graph(self, runtime, snapshot, ctx):
        graph = StateGraph(_State)
        graph.add_node("snapshot", _safe_node(self._snapshot_node(runtime, snapshot, ctx)))
        for stage in ("collect", "analyze"):
            graph.add_node(stage, self._subgraph(stage, runtime, snapshot, ctx))
        graph.add_node("notify", self._notification_graph(runtime, snapshot))
        for stage in ("aggregate", "finish"):
            graph.add_node(stage, self._phase_node(stage, runtime, snapshot))
        for stage in _STAGES:

            async def start_body(state, stage=stage):
                return {"status": "running"}

            graph.add_node(
                f"start_{stage}",
                archive_node(
                    runtime,
                    scope="parent",
                    stage=stage,
                    key=f"started:{stage}",
                    operation=start_body,
                    category=None,
                    summarize=lambda body: body,
                    publish=lambda key, summary: {},
                ),
            )
            graph.add_edge(f"start_{stage}", stage)
        graph.add_edge(START, "snapshot")
        graph.add_edge("snapshot", "start_collect")
        for before, after in (
            ("collect", "analyze"),
            ("analyze", "aggregate"),
            ("aggregate", "notify"),
        ):
            graph.add_conditional_edges(
                before,
                lambda state, after=after: "finish" if state["stopped"] else after,
                {"finish": "start_finish", after: f"start_{after}"},
            )
        graph.add_edge("notify", "start_finish")
        graph.add_edge("finish", END)
        return graph.compile(checkpointer=self._checkpointer)

    def _subgraph(self, stage, runtime, snapshot, ctx):
        wf = snapshot.workflow
        graph = StateGraph(_ChildState)
        keys = wf.sources if stage == "collect" else [task.id for task in wf.analyses]
        concurrency = wf.collection_concurrency if stage == "collect" else wf.analysis_concurrency
        semaphore = asyncio.Semaphore(concurrency)
        for ident in keys:

            async def operation(state, ident=ident):
                if stage == "collect":
                    config = snapshot.sources[ident]
                    try:
                        async with asyncio.timeout(config.timeout):
                            raw = await self.collector_manager.collect(copy_model(config), ctx)
                        if asyncio.current_task().cancelling():
                            raise asyncio.CancelledError
                        result = CollectionResult.model_validate(
                            raw.model_dump(mode="json")
                            if isinstance(raw, CollectionResult)
                            else raw
                        )
                        if result.source_id != ident:
                            raise ValueError("Collector identity mismatch")
                    except TimeoutError:
                        result = CollectionResult(
                            source_id=ident,
                            status="timeout",
                            error=ErrorInfo(code="collection_timeout", message="来源采集超时"),
                        )
                    except Exception as exc:
                        result = CollectionResult(
                            source_id=ident,
                            status="failed",
                            error=exception_error(
                                exc, code="collection_failed", message="来源采集失败"
                            ),
                        )
                else:
                    incoming = await self._result(runtime, snapshot, state, required=("collect",))
                    task = next(task for task in wf.analyses if task.id == ident)
                    result = await self._analysis_call(
                        snapshot.ai[task.ai], task.prompt, incoming.shared_input, ident, incoming, task.model
                    )
                return result.model_dump(mode="json")

            archived = archive_node(
                runtime,
                scope=stage,
                stage=stage,
                key=lambda state: state["archive_key"],
                operation=operation,
                category="collection" if stage == "collect" else "analysis",
                summarize=lambda body: {"item_status": body["status"]},
                publish=lambda key, summary, ident=ident: {"items": {ident: key}},
            )

            async def bounded(state, archived=archived, ident=ident):
                async with semaphore:
                    key = await asyncio.to_thread(self._item_key, runtime, stage, ident, state)
                    return await archived({**state, "archive_key": key})

            graph.add_node(f"work_{ident}", _safe_node(bounded))
            graph.add_edge(START, f"work_{ident}")
            graph.add_edge(f"work_{ident}", "arrange")
        graph.add_node("arrange", self._phase_node(stage, runtime, snapshot))
        graph.add_edge("arrange", END)
        return graph.compile()

    @staticmethod
    def _item_key(runtime, stage, ident, state):
        base = f"{stage}:item:{ident}"
        generation = state.get("generation", 0)
        if not generation:
            return base
        _, entries = runtime.store.entries(runtime.session_id)
        successful = next(
            (
                entry
                for entry in entries
                if entry["scope"] == stage
                and (
                    entry["write_key"] == base or entry["write_key"].startswith(base + ":attempt:")
                )
                and entry["summary"].get("item_status") == "success"
            ),
            None,
        )
        return successful["write_key"] if successful else f"{base}:attempt:{generation}"

    def _phase_node(self, stage, runtime, snapshot):
        async def operation(state):
            required = {
                "analyze": ("collect",),
                "aggregate": ("analyze",),
                "notify": ("aggregate",),
            }.get(stage, ())
            incoming = await self._result(runtime, snapshot, state, required=required)
            if (
                stage == "aggregate"
                and snapshot.workflow.fan_in
                and "$input" in snapshot.workflow.fan_in.order
            ):
                incoming = await self._result(
                    runtime, snapshot, state, required=("collect", "analyze")
                )
            incoming.stage = stage
            if stage == "collect":
                incoming.collection = [
                    CollectionResult.model_validate(await runtime.read(state["items"][ident]))
                    for ident in snapshot.workflow.sources
                ]
                return self._arrange_collection(incoming, snapshot)
            if stage == "analyze":
                incoming.analyses = [
                    AnalysisResult.model_validate(await runtime.read(state["items"][task.id]))
                    for task in snapshot.workflow.analyses
                ]
                return self._arrange_analysis(incoming, snapshot)
            if stage == "aggregate":
                return await self._aggregate(incoming, snapshot)
            if stage == "notify":
                return await self._notify(incoming, snapshot, runtime)
            return await self._finish(incoming, runtime)

        categories = {"collect": "collection", "analyze": "analysis", "aggregate": "final"}

        def summarize(body):
            return {
                "stopped": body.get("stopped", False),
                "status": body.get("status", "running"),
                "degraded": body.get("degraded", False),
            }

        return _safe_node(
            archive_node(
                runtime,
                scope="phase",
                stage=stage,
                key=lambda state: (
                    f"phase:{stage}"
                    + (f":attempt:{state['generation']}" if state.get("generation") else "")
                ),
                operation=operation,
                category=categories.get(stage),
                summarize=summarize,
                publish=lambda key, summary: {
                    "phases": {stage: key},
                    "stopped": summary["stopped"],
                    "status": summary["status"],
                    **(
                        {"retry_stage": stage}
                        if summary["status"] == "failed"
                        and stage in {"collect", "analyze", "aggregate"}
                        else {}
                    ),
                },
            )
        )

    @staticmethod
    def _halt(result, code, message):
        result.stopped, result.status = True, "failed"
        result.errors.append(ErrorInfo(code=code, message=message))

    def _arrange_collection(self, result, snapshot):
        wf = snapshot.workflow
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
                break
        if not valid and not result.stopped:
            if wf.on_all_empty == "stop":
                self._halt(result, "all_empty", "所有来源均无有效内容")
            else:
                result.stopped = True
        return {
            "collection": [item.model_dump(mode="json") for item in result.collection],
            "shared_input": result.shared_input,
            "stopped": result.stopped,
            "status": result.status,
            "errors": [e.model_dump(mode="json") for e in result.errors],
        }

    def _arrange_analysis(self, result, snapshot):
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

    async def _analysis_call(self, config, prompt, text, task_id, result, model):
        try:
            async with asyncio.timeout(config.timeout):
                kwargs = {"model": model, "task_id": task_id, "context": ExecutionContext(
                    workflow_id=result.workflow_id, session_id=result.session_id, stage=result.stage,
                )}
                raw = await self.ai_service.execute(copy_model(config), prompt, text, **kwargs)
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
        wf = snapshot.workflow
        if wf.fan_in is None:
            result.outputs = {
                item.task_id: item.text for item in result.analyses if item.status == "success"
            }
        else:
            by_id = {item.task_id: item for item in result.analyses}
            parts = []
            for key in wf.fan_in.order or [task.id for task in wf.analyses]:
                if key == "$input":
                    parts.append(result.shared_input)
                elif by_id[key].status == "success":
                    parts.append(by_id[key].text)
                elif wf.fan_in.mark_incomplete:
                    parts.append(f"[{key}: incomplete]")
            text = wf.fan_in.separator.join(parts)
            if not text.strip():
                self._halt(result, "aggregate_empty", "汇总未产生有效正文")
            elif wf.fan_in.ai:
                result.aggregate = await self._analysis_call(
                    snapshot.ai[wf.fan_in.ai], wf.fan_in.prompt, text, "final", result, wf.fan_in.model
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

    def _notification_graph(self, runtime, snapshot):
        graph = StateGraph(_State)
        wf = snapshot.workflow
        output_ids = ["final"] if wf.fan_in else [task.id for task in wf.analyses]
        fresh_intents = set()
        previous = START
        for output_index, output_id in enumerate(output_ids):
            for channel_index, cid in enumerate(wf.channels):
                intent_key = f"intent:{output_id}:{cid}"
                receipt_key = f"delivery:{output_id}:{cid}"

                async def intention(state, oid=output_id, cid=cid, key=intent_key):
                    fresh_intents.add(key)
                    return {"output_id": oid, "channel_id": cid}

                intent_archive = archive_node(
                    runtime,
                    scope="notification",
                    stage="notify",
                    key=intent_key,
                    category=None,
                    operation=intention,
                    publish=lambda key, summary: {},
                )

                async def intent_node(state, oid=output_id, archived=intent_archive):
                    result = await self._result(runtime, snapshot, state, required=("aggregate",))
                    if oid not in result.outputs:
                        return {}
                    return await archived(state)

                async def delivery(state, oid=output_id, cid=cid, ikey=intent_key):
                    result = await self._result(runtime, snapshot, state, required=("aggregate",))
                    note = next(note for note in result.notifications if note.output_id == oid)
                    config = snapshot.channels[cid]
                    if not config.enabled:
                        receipt = DeliveryResult(
                            channel_id=cid, output_id=oid, status="skipped", attempts=0
                        )
                    elif ikey not in fresh_intents:
                        receipt = self._uncertain(cid, oid)
                    else:
                        try:
                            async with asyncio.timeout(config.timeout):
                                raw = await self.channel_manager.send(
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
                            receipt = self._uncertain(cid, oid)
                            receipt.status = "timeout"
                        except Exception:
                            receipt = self._uncertain(cid, oid)
                    return receipt.model_dump(mode="json")

                receipt_archive = archive_node(
                    runtime,
                    scope="notification",
                    stage="notify",
                    key=receipt_key,
                    category=None,
                    operation=delivery,
                    publish=lambda key, summary: {},
                )

                async def receipt_node(state, oid=output_id, archived=receipt_archive):
                    result = await self._result(runtime, snapshot, state, required=("aggregate",))
                    if oid not in result.outputs:
                        return {}
                    return await archived(state)

                intent_name, receipt_name = (
                    f"intent_{output_index}_{channel_index}",
                    f"receipt_{output_index}_{channel_index}",
                )
                graph.add_node(intent_name, _safe_node(intent_node))
                graph.add_node(receipt_name, _safe_node(receipt_node))
                graph.add_edge(previous, intent_name)
                graph.add_edge(intent_name, receipt_name)
                previous = receipt_name
        graph.add_node("arrange", self._phase_node("notify", runtime, snapshot))
        graph.add_edge(previous, "arrange")
        graph.add_edge("arrange", END)
        return graph.compile()

    async def _notify(self, result, snapshot, runtime):
        receipts = []
        for note in result.notifications:
            for cid in snapshot.workflow.channels:
                receipts.append(await runtime.read(f"delivery:{note.output_id}:{cid}"))
        return {"deliveries": receipts}

    async def _finish(self, result, runtime):
        _, entries = await asyncio.to_thread(runtime.store.entries, runtime.session_id)
        degraded = any(e["summary"].get("backup_failed") for e in entries)
        degraded |= any(
            item.status in {"failed", "missing", "timeout"} for item in result.collection
        )
        degraded |= any(item.status != "success" for item in result.analyses)
        degraded |= any(item.status in {"failed", "timeout"} for item in result.deliveries)
        status = "failed" if result.status == "failed" else "partial" if degraded else "completed"
        return {"status": status, "stopped": result.stopped}
