"""Workflow 的运行准入、唯一事件流与任务生命周期。

LangGraph 管理图内执行和 checkpoint；订阅派生业务事实，storage 组装报告。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import aclosing
from pathlib import Path
from weakref import WeakValueDictionary

from langgraph.types import Overwrite
from pydantic import TypeAdapter

from logagent.errors import LogAgentError, exception_error
from logagent.models import (
    ID,
    CollectionContext,
    WorkflowSnapshot,
    copy_model,
)
from logagent.workflow.execution.context import WorkflowContext, _call, capture_snapshot
from logagent.workflow.execution.tasks import RunCoordinator
from logagent.workflow.storage.checkpoints import WorkflowSqliteSaver
from logagent.workflow.storage.facts import SessionStore
from logagent.workflow.storage.reports import assemble_result
from logagent.workflow.storage.sessions import SessionView
from logagent.workflow.stream.subscriptions.checkpoints import CheckpointArchive
from logagent.workflow.stream.subscriptions.progress import ProgressHub

logger = logging.getLogger("logagent.workflow")
_STAGES = ("collect", "analyze", "aggregate", "notify", "finish")
_ID = TypeAdapter(ID)


class WorkflowRunner:
    """编排采集、分析、汇总和通知，提供运行及只读查询入口。

    LangGraph 保存执行进度，SessionStore 保存派生的不可变业务事实。
    外部能力由构造参数注入，当前协调范围为单执行器进程。
    """

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
        """绑定业务依赖、存储和运行协调器。

        未注入业务存储时创建持久化 SQLite 文件，并在关闭时负责释放；
        调用方注入的存储由调用方关闭。默认最多同时执行 4 个运行。
        """
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
        self.graph = None
        self._start_lock = asyncio.Lock()
        self._admission_lock = asyncio.Lock()
        self._session_locks = WeakValueDictionary()
        self.progress_hub = ProgressHub()
        self._cleanup = None
        self.archive = None
        self._shutdown = False
        self._shutdown_task: asyncio.Task | None = None

    async def start(self):
        """串行初始化自有 checkpointer；初始化失败释放上下文并继续抛错。"""
        async with self._start_lock:
            if self._shutdown:
                raise LogAgentError("shutdown", "Workflow 已关闭")
            if self._checkpointer is None:
                self._saver_context = WorkflowSqliteSaver.from_conn_string(self.database)
                try:
                    self._checkpointer = await self._saver_context.__aenter__()
                    await self._checkpointer.setup()
                except BaseException:
                    await self._saver_context.__aexit__(None, None, None)
                    self._checkpointer, self._saver_context = None, None
                    raise
            if self.graph is None:
                from logagent.workflow.graph.workflow import build_workflow

                self.graph = build_workflow(checkpointer=self._checkpointer)
            if self.archive is None:
                self.archive = CheckpointArchive(
                    self._checkpointer,
                    self.session_store,
                    self.session_view,
                    self.progress_hub.publish,
                )
                from logagent.workflow.execution.maintenance import CheckpointCleanup

                self._cleanup = CheckpointCleanup(
                    self._checkpointer,
                    self.session_lock,
                    capacity=self.coordinator._max,
                    archive=self.archive,
                    store=self.session_store,
                    active=self.coordinator.contains,
                    publish=self.progress_hub.publish,
                )
                for sid in await asyncio.to_thread(self.session_store.session_ids):
                    await self._cleanup.request(sid)

    def session_lock(self, sid):
        return self._session_locks.setdefault(sid, asyncio.Lock())

    async def pause_admission(self):
        """关闭准入并等待已进入准入区的请求提交或失败，返回活动运行数。"""
        async with self._admission_lock:
            self.coordinator.accepting = False
            return self.coordinator.active

    def resume_admission(self):
        """服务尚未关闭时重新允许新运行进入。"""
        if not self._shutdown:
            self.coordinator.accepting = True

    async def validate(self, workflow):
        """复制输入，并对完整快照中的来源、AI 和渠道配置调用各自校验器。

        当前实现仅处理 WorkflowSnapshot，其他输入类型不执行校验。
        """
        value = copy_model(workflow)
        if isinstance(value, WorkflowSnapshot):
            for source in value.sources.values():
                self.collector_manager.validate(source)
            for config in value.ai.values():
                self.ai_service.validate(config)
            for channel in value.channels.values():
                self.channel_manager.validate(channel)

    async def save(self, workflow, **kwargs):
        """委托资源仓库保存 Workflow；未注入仓库时明确报错。"""
        if self.resource_store is None:
            raise LogAgentError("configuration_unavailable", "未注入资源仓库")
        return await _call(self.resource_store.save, "workflows", workflow, **kwargs)

    async def trigger(self, workflow, *, session_id=None, context=None):
        """固定配置、建立业务记录并提交后台运行，返回 session_id。

        准入锁覆盖容量检查、快照存档和任务提交；返回前 session 已可查询。
        已有 session、禁用定义或不匹配的上下文会被拒绝。
        """
        sid = session_id or uuid.uuid4().hex
        _ID.validate_python(sid)
        await self.start()
        async with self._admission_lock:
            self.coordinator.check(sid)
            if await asyncio.to_thread(self.session_store.entry, sid, "created") is not None:
                raise LogAgentError("session_exists", "session 已存在")
            snapshot = await capture_snapshot(workflow, self.resource_store)
            if not snapshot.workflow.enabled:
                raise LogAgentError("workflow_disabled", "Workflow 已禁用")
            if context and (
                context.session_id != sid or context.workflow_id != snapshot.workflow.id
            ):
                raise LogAgentError("invalid_argument", "运行上下文与 session 不匹配")
            await asyncio.to_thread(
                self.session_store.create,
                sid,
                snapshot.workflow.id,
                snapshot.workflow.backup,
                workflow_name=snapshot.workflow.name,
            )
            ctx = context or CollectionContext(
                snapshot.workflow.id, sid, self.log_path, self.credentials, self.session_view
            )
            execution_epoch = uuid.uuid4().hex
            self.coordinator.submit(
                sid,
                lambda: self._execute(
                    sid,
                    snapshot,
                    ctx,
                    resume=False,
                    execution_epoch=execution_epoch,
                ),
            )
        return sid

    async def _recovery_material(self, session_id, *, stage=None, checkpoint_id=None):
        from logagent.workflow.execution.recovery import prepare_recovery

        return await prepare_recovery(
            session_id,
            saver=self._checkpointer,
            store=self.session_store,
            view=self.session_view,
            graph=self.graph,
            stage=stage,
            checkpoint_id=checkpoint_id,
        )

    async def recovery_availability(self, session_id, *, stage=None, checkpoint_id=None):
        """使用与实际 resume 相同的入口和材料检查，不写入历史。"""
        from logagent.models import RecoveryAvailability

        _ID.validate_python(session_id)
        await self.start()
        await self.session_view.get_session(session_id)
        async with self.session_lock(session_id), self._admission_lock:
            try:
                self.coordinator.check(session_id)
                _, _, _, selected = await self._recovery_material(
                    session_id, stage=stage, checkpoint_id=checkpoint_id
                )
            except LogAgentError as exc:
                return RecoveryAvailability(
                    available=False,
                    reason=exc.info,
                    checkpoint_expires_at=(exc.info.details or {}).get("checkpoint_expires_at"),
                )
        return RecoveryAvailability(
            available=True,
            checkpoint_expires_at=await asyncio.to_thread(
                self.session_store.checkpoint_deadline,
                session_id,
                selected.values["execution_epoch"],
            ),
        )

    async def resume(
        self, session_id, *, stage=None, checkpoint_id=None, request_id=None, context=None
    ):
        """原 thread 中断续跑，或由父图入口重做阶段及后续流程。"""
        from logagent.workflow.execution.recovery import find_request
        from logagent.workflow.graph.workflow import PREDECESSORS

        _ID.validate_python(session_id)
        if request_id is not None:
            _ID.validate_python(request_id)
        await self.start()
        async with self.session_lock(session_id), self._admission_lock:
            previous = None
            if request_id is not None:
                previous = await find_request(self._checkpointer, session_id, request_id)
                if previous:
                    if (
                        previous.get("resume_stage") != stage
                        or previous.get("resume_checkpoint") != checkpoint_id
                    ):
                        raise LogAgentError("request_conflict", "同一请求标识已用于不同的恢复参数")
                    if self.coordinator.contains(session_id):
                        return session_id
                    latest = await self._checkpointer.aget_tuple(
                        {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}},
                    )
                    if (
                        latest.checkpoint["channel_values"]["execution_epoch"]
                        != previous["execution_epoch"]
                    ):
                        return session_id
                    # checkpoint 已受理但任务提交前可能强退；仅续接原轮次。
                    stage, checkpoint_id = None, None
            self.coordinator.check(session_id)
            snapshot, saved_path, graph, saved = await self._recovery_material(
                session_id,
                stage=stage,
                checkpoint_id=checkpoint_id,
            )
            if previous and not saved.next:
                return session_id
            if context and (
                context.log_path != saved_path
                or context.session_id != session_id
                or context.workflow_id != snapshot.workflow.id
            ):
                raise LogAgentError("invalid_argument", "恢复不能替换原运行上下文")
            context = context or CollectionContext(
                snapshot.workflow.id,
                session_id,
                saved_path,
                self.credentials,
                self.session_view,
            )
            config = {"configurable": {"thread_id": session_id}}
            if stage is not None:
                execution_epoch = uuid.uuid4().hex
                kept = _STAGES[: _STAGES.index(stage)]
                origins = {
                    name: saved.values.get("stage_origins", {}).get(
                        name, saved.values["execution_epoch"]
                    )
                    for name in kept
                }
                reset = {
                    "intents": {},
                    "deliveries": {},
                    "phase": {},
                    "outputs": {},
                    "aggregate_meta": None,
                }
                if stage == "notify":
                    reset["outputs"] = saved.values["outputs"]
                if stage in {"collect", "analyze"}:
                    reset["analysis_items"] = {}
                if stage == "collect":
                    reset["shared_input"] = ""
                config = await graph.aupdate_state(
                    saved.config,
                    {
                        **reset,
                        "stage_origins": origins,
                        "execution_epoch": Overwrite(execution_epoch),
                        "stopped": False,
                        "status": "running",
                        "error": None,
                        "resume_request_id": request_id,
                        "resume_stage": stage,
                        "resume_checkpoint": checkpoint_id,
                    },
                    as_node=PREDECESSORS[stage],
                )
                await self.archive.reconcile(session_id)
            self.coordinator.submit(
                session_id,
                lambda: self._execute(
                    session_id,
                    snapshot,
                    context,
                    resume=True,
                    config=config,
                ),
            )
        return session_id

    async def wait(self, session_id):
        """通过协调器等待运行结果或抛出运行错误，不查询持久历史。"""
        return await self.coordinator.wait(session_id)

    async def get_session(self, session_id, *, version=None):
        """通过只读视图取得最新或指定业务版本的 session 摘要。"""
        return await self.session_view.get_session(session_id, version=version)

    async def list_sessions(self, workflow_id=None, **kwargs):
        """将过滤和分页条件交给只读 session 视图。"""
        return await self.session_view.list_sessions(workflow_id, **kwargs)

    async def history(self, session_id):
        """返回按版本排序的业务存档条目，移除内部完整性摘要 digest。"""
        _, entries = await asyncio.to_thread(self.session_store.entries, session_id)
        return [{k: value for k, value in entry.items() if k != "digest"} for entry in entries]

    async def cancel(self, session_id):
        """按 session_id 转交显式取消请求，返回是否请求到活动任务。"""
        return await self.coordinator.cancel(session_id)

    async def reconcile_interrupted(self):
        """将未被本进程持有的 created/running 记录标记为 interrupted。

        供应用启动协调使用，只补记中断事实，不自动恢复或重跑。
        """

        await self.start()
        offset = 0
        while records := await self.list_sessions(limit=1000, offset=offset):
            for record in records:
                if record.status not in {"created", "running"} or self.coordinator.contains(
                    record.session_id
                ):
                    continue
                header, _ = await asyncio.to_thread(self.session_store.entries, record.session_id)
                await self._event(
                    record.session_id,
                    f"interrupted:{record.version}",
                    record.stage,
                    "interrupted",
                    execution_epoch=record.execution_epoch,
                )
            offset += len(records)

    async def shutdown(self):
        """共享关闭任务，调用者取消等待不会打断资源释放；失败后允许重试。"""
        if self._shutdown_task is None or (
            self._shutdown_task.done() and self._shutdown_task.exception() is not None
        ):
            self._shutdown_task = asyncio.create_task(self._shutdown_once())
        await asyncio.shield(self._shutdown_task)

    async def _shutdown_once(self):
        """先停止准入和活动运行，再释放自有 checkpointer 与业务存储。"""
        async with self._start_lock:
            await self.pause_admission()
            self._shutdown = True
        await self.coordinator.shutdown()
        if self._cleanup is not None:
            await self._cleanup.close()
        await self.progress_hub.close()
        if self._saver_context is not None:
            await self._saver_context.__aexit__(None, None, None)
            self._saver_context = None
        if self._owns_store:
            await asyncio.to_thread(self.session_store.close)

    async def _event(self, sid, key, stage, status, error=None, *, execution_epoch=None):
        summary = {
            "status": status,
            "error": error.model_dump(mode="json") if error else None,
            "execution_epoch": execution_epoch,
        }
        await asyncio.to_thread(
            self.session_store.write, sid, key, stage=stage, scope="parent", summary=summary
        )
        await self.progress_hub.publish(await self.get_session(sid))

    async def _execute(self, sid, snapshot, context, *, resume, config=None, execution_epoch=None):
        from logagent.workflow.graph.workflow import GRAPH_REVISION

        ctx = context or CollectionContext(
            snapshot.workflow.id, sid, self.log_path, self.credentials, self.session_view
        )
        config = config or {"configurable": {"thread_id": sid}}
        graph = self.graph
        state = {
            "session_id": sid,
            "snapshot": snapshot.model_dump(mode="json"),
            "log_path": ctx.log_path,
            "graph_revision": GRAPH_REVISION,
            "execution_epoch": execution_epoch,
            "stopped": False,
            "status": "running",
            "degraded": False,
            "error": None,
            "phase": {},
            "shared_input": "",
            "analysis_items": {},
            "outputs": {},
            "intents": {},
            "deliveries": {},
            "stage_origins": {},
        }
        try:
            await self.archive.reconcile(sid)
            if resume:
                saved = await graph.aget_state(config)
                state = saved.values
                if saved.next:
                    record = await self.get_session(sid)
                    await self._event(
                        sid,
                        f"resumed:{record.version}",
                        record.stage,
                        "running",
                        execution_epoch=state["execution_epoch"],
                    )
                if not saved.next:
                    return await self._settled_result(sid, snapshot, state)
            from logagent.workflow.stream.subscriptions.checkpoints import CheckpointSubscription

            runtime_context = WorkflowContext(
                snapshot=snapshot,
                collection=ctx,
                collector_manager=self.collector_manager,
                ai_service=self.ai_service,
                channel_manager=self.channel_manager,
                finalize=self._cleanup.finalize,
            )
            await run_graph(
                graph,
                None if resume else state,
                config,
                session_id=sid,
                context=runtime_context,
                consume=CheckpointSubscription(self.archive, snapshot, state, runtime_context),
            )
            await self.archive.reconcile(sid)
            saved = await graph.aget_state({"configurable": {"thread_id": sid}})
            return await self._settled_result(sid, snapshot, saved.values)
        except asyncio.CancelledError:
            await self.archive.reconcile(sid)
            saved = await graph.aget_state({"configurable": {"thread_id": sid}})
            result = await assemble_result(self.session_view, sid, snapshot, saved.values or state)
            result.status, result.cancelled = "cancelled", True
            record = await self.get_session(sid)
            await self._event(
                sid,
                f"cancelled:{record.version}",
                result.stage,
                "cancelled",
                execution_epoch=result_epoch(saved.values or state),
            )
            return result
        except Exception as exc:
            error = (
                exc.info
                if isinstance(exc, LogAgentError)
                else exception_error(exc, code="workflow_failed", message="Workflow 执行或归档失败")
            )
            try:
                record = await self.get_session(sid)
                await self._event(
                    sid,
                    f"interrupted:{record.version}",
                    record.stage,
                    "interrupted",
                    error,
                    execution_epoch=state.get("execution_epoch"),
                )
            except Exception:
                logger.exception("Unable to persist interrupted session", extra={"session_id": sid})
            raise
        finally:
            # Enqueue before returning; the worker waits for this task before checking
            # activity. Backpressure never drops a completed run's maintenance request.
            await self._cleanup.request(sid, completion=asyncio.current_task())

    async def _settled_result(self, sid, snapshot, state):
        record = await self.get_session(sid)
        status = state.get("status", "running")
        if record.status in {"cancelled", "interrupted", "running"} and status in {
            "completed",
            "partial",
            "failed",
        }:
            await self._event(
                sid,
                f"settled:{record.version}",
                "finish",
                status,
                execution_epoch=state["execution_epoch"],
            )
        return await assemble_result(self.session_view, sid, snapshot, state)


def result_epoch(state):
    return state.get("execution_epoch")


async def run_graph(graph, state, config, *, session_id, context, consume):
    """None 输入沿用 LangGraph 恢复语义；异常关闭事件源并收尾执行。"""
    configured = config.get("configurable", {})
    if configured.get("thread_id", session_id) != session_id:
        raise ValueError("Workflow thread_id must equal sessionID")
    config = {
        **config,
        "configurable": {**configured, "thread_id": session_id},
        "metadata": {**config.get("metadata", {}), "sessionID": session_id},
    }
    try:
        async with aclosing(
            graph.astream_events(
                state,
                config=config,
                context=context,
                version="v2",
                subgraphs=True,
                stream_mode=["updates", "checkpoints"],
                durability="sync",
            )
        ) as events:
            async for event in events:
                await consume(event)
    except BaseException as exc:
        context.abort_intents(exc)
        raise
