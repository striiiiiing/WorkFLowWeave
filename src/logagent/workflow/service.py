"""Workflow 运行编排：固定快照、执行阶段图、记录业务事实并恢复原运行。

LangGraph checkpoint 管理控制进度，SessionStore 保存独立可读的业务存档；
两者通过稳定引用衔接，不假设跨存储事务。阅读顺序可从 trigger、_execute、
_graph 进入各节点，再检查 resume 与通知意图/回执的恢复边界。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from weakref import WeakValueDictionary

from pydantic import TypeAdapter

from logagent.errors import LogAgentError, exception_error
from logagent.models import (
    ID,
    CollectionContext,
    ErrorInfo,
    Notification,
    WorkflowDefinition,
    WorkflowSnapshot,
    copy_model,
)
from logagent.workflow.archive import CheckpointArchive
from logagent.workflow.checkpoints import WorkflowSqliteSaver
from logagent.workflow.result import WorkflowResult
from logagent.workflow.session_store import SessionStore
from logagent.workflow.session_view import SessionView
from logagent.workflow.stream import ProgressHub

logger = logging.getLogger("logagent.workflow")
_STAGES = ("collect", "analyze", "aggregate", "notify", "finish")
_ID = TypeAdapter(ID)


async def _call(fn: Callable, *args, **kwargs):
    """调用注入的同步或异步接口，统一返回实际结果。"""
    value = fn(*args, **kwargs)
    return await value if inspect.isawaitable(value) else value




class RunCoordinator:
    """管理进程内运行任务、容量与取消，不承担持久历史查询。

    最近 32 个完成任务保留为有限等待窗口，包含运行异常；
    长期业务历史由 SessionStore 保存，避免任务正文在内存中无界积累。
    """
    COMPLETED_LIMIT = 32

    def __init__(self, *, max_concurrent_runs=4):
        """初始化任务集合和准入状态；并发容量必须为正整数。"""
        if type(max_concurrent_runs) is not int or max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be positive")
        self._max = max_concurrent_runs
        self._tasks: dict[str, asyncio.Task] = {}
        self._completed: OrderedDict[str, asyncio.Task] = OrderedDict()
        self._started: dict[str, asyncio.Event] = {}
        self.accepting = True

    @property
    def active(self):
        """返回仍在活动任务集合中的运行数量。"""
        return len(self._tasks)

    def contains(self, sid):
        """判断指定 session 是否仍由活动任务集合持有。"""
        return sid in self._tasks

    def check(self, sid):
        """检查准入开关、同 session 互斥和全局容量，拒绝时抛出业务错误。"""
        if not self.accepting:
            raise LogAgentError("not_ready", "Workflow 未开放运行准入")
        if sid in self._tasks:
            raise LogAgentError("session_active", "同一 session 已在运行")
        if self.active >= self._max:
            raise LogAgentError("capacity_exhausted", "运行容量已满")

    def submit(self, sid, operation):
        """创建并持有后台任务；完成后移入有界等待窗口。"""
        self.check(sid)
        started = self._started[sid] = asyncio.Event()

        async def run():
            """标记协程已启动，再进入实际运行的异常处理边界。"""
            started.set()
            return await operation()

        def done(task):
            """清理活动句柄并取出异常，避免无人等待的任务异常丢失诊断。"""
            self._tasks.pop(sid, None)
            self._started.pop(sid, None)
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
        """等待活动或近期完成任务；调用者取消等待不会取消后台运行。

        结果离开内存窗口后抛出 session_not_active，应改用 session 查询。
        """
        task = self._tasks.get(sid) or self._completed.get(sid)
        if task is None:
            raise LogAgentError("session_not_active", "运行结果已离开内存等待窗口，请查询 session")
        return await asyncio.shield(task)

    async def cancel(self, sid):
        """请求取消活动任务，返回是否发出了取消请求。

        先等待任务启动，使其有机会进入异常处理边界并记录取消事件；
        返回 True 不代表任务已结束，结束结果由 wait 获取。
        """
        task = self._tasks.get(sid)
        if task is None or task.done():
            return False
        await self._started[sid].wait()
        task.cancel()
        return True

    async def shutdown(self):
        """关闭准入，取消全部活动任务并等待它们收尾。"""
        self.accepting = False
        tasks = list(self._tasks.values())
        for sid in list(self._tasks):
            await self.cancel(sid)
        await asyncio.gather(*tasks, return_exceptions=True)


class WorkflowService:
    """编排采集、分析、汇总和通知，提供运行及只读查询入口。

    LangGraph 保存执行进度，SessionStore 保存业务事实；两者通过稳定
    存档引用关联。外部能力由构造参数注入，当前协调范围为单执行器进程。
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
            if self.archive is None:
                self.archive = CheckpointArchive(self._checkpointer, self.session_store,
                                                 self.session_view, self.progress_hub.publish)
                from logagent.workflow.checkpoints import CheckpointCleanup
                self._cleanup = CheckpointCleanup(self._checkpointer, self.session_lock,
                    capacity=self.coordinator._max, archive=self.archive, store=self.session_store,
                    active=self.coordinator.contains, publish=self.progress_hub.publish)
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

    async def _snapshot(self, workflow):
        """复制完整快照或按已保存 ID 生成快照，拒绝直接触发裸定义。"""
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
            snapshot = await self._snapshot(workflow)
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
            self.coordinator.submit(sid, lambda: self._execute(
                sid, snapshot, ctx, resume=False, execution_epoch=execution_epoch,
            ))
        return sid

    async def _recovery_material(self, session_id, *, stage=None, checkpoint_id=None):
        from logagent.workflow.recovery import prepare_recovery

        return await prepare_recovery(self, session_id, stage=stage, checkpoint_id=checkpoint_id)

    async def recovery_availability(self, session_id, *, stage=None, checkpoint_id=None):
        """使用与实际 resume 相同的入口和材料检查，不写入历史。"""
        from logagent.models import RecoveryAvailability

        _ID.validate_python(session_id)
        await self.start()
        await self.session_view.get_session(session_id)
        async with self.session_lock(session_id), self._admission_lock:
            try:
                self.coordinator.check(session_id)
                _, _, _, selected = await self._recovery_material(session_id, stage=stage, checkpoint_id=checkpoint_id)
            except LogAgentError as exc:
                return RecoveryAvailability(available=False, reason=exc.info,
                    checkpoint_expires_at=(exc.info.details or {}).get("checkpoint_expires_at"))
        return RecoveryAvailability(available=True, checkpoint_expires_at=await asyncio.to_thread(self.session_store.checkpoint_deadline, session_id, selected.values["execution_epoch"]))

    async def resume(self, session_id, *, stage=None, checkpoint_id=None, request_id=None,
                     context=None):
        """原 thread 中断续跑，或由父图入口重做阶段及后续流程。"""
        from logagent.workflow.graph import PREDECESSORS
        from logagent.workflow.recovery import find_request

        _ID.validate_python(session_id)
        if request_id is not None:
            _ID.validate_python(request_id)
        await self.start()
        async with self.session_lock(session_id), self._admission_lock:
            previous = None
            if request_id is not None:
                previous = await find_request(self._checkpointer, session_id, request_id)
                if previous:
                    if previous.get("resume_stage") != stage or previous.get("resume_checkpoint") != checkpoint_id:
                        raise LogAgentError("request_conflict", "同一请求标识已用于不同的恢复参数")
                    if self.coordinator.contains(session_id):
                        return session_id
                    latest = await self._checkpointer.aget_tuple(
                        {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}},
                    )
                    if latest.checkpoint["channel_values"]["execution_epoch"] != previous["execution_epoch"]:
                        return session_id
                    # checkpoint 已受理但任务提交前可能强退；仅续接原轮次。
                    stage, checkpoint_id = None, None
            self.coordinator.check(session_id)
            snapshot, saved_path, graph, saved = await self._recovery_material(
                session_id, stage=stage, checkpoint_id=checkpoint_id,
            )
            if previous and not saved.next:
                return session_id
            if context and (
                context.log_path != saved_path or context.session_id != session_id
                or context.workflow_id != snapshot.workflow.id
            ):
                raise LogAgentError("invalid_argument", "恢复不能替换原运行上下文")
            context = context or CollectionContext(
                snapshot.workflow.id, session_id, saved_path, self.credentials, self.session_view,
            )
            config = {"configurable": {"thread_id": session_id}}
            if stage is not None:
                execution_epoch = uuid.uuid4().hex
                kept = _STAGES[:_STAGES.index(stage)]
                origins = {name: saved.values.get("stage_origins", {}).get(name, saved.values["execution_epoch"]) for name in kept}
                reset = {"intents": {}, "deliveries": {}, "phase": {}, "outputs": {}, "aggregate_meta": None}
                if stage == "notify":
                    reset["outputs"] = saved.values["outputs"]
                if stage in {"collect", "analyze"}:
                    reset["analysis_items"] = {}
                if stage == "collect":
                    reset["shared_input"] = ""
                config = await graph.aupdate_state(saved.config, {
                    **reset, "stage_origins": origins, "execution_epoch": execution_epoch,
                    "stopped": False, "status": "running", "error": None,
                    "resume_request_id": request_id, "resume_stage": stage,
                    "resume_checkpoint": checkpoint_id,
                }, as_node=PREDECESSORS[stage])
                await self.archive.reconcile(session_id)
            self.coordinator.submit(
                session_id, lambda: self._execute(
                    session_id, snapshot, context, resume=True, config=config,
                ),
            )
        return session_id

    recover = resume

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
                await self._event(record.session_id, f"interrupted:{record.version}",
                                  record.stage, "interrupted", execution_epoch=record.execution_epoch)
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
        summary = {"status": status, "error": error.model_dump(mode="json") if error else None,
                   "execution_epoch": execution_epoch}
        await asyncio.to_thread(self.session_store.write, sid, key, stage=stage, scope="parent", summary=summary)
        await self.progress_hub.publish(await self.get_session(sid))

    async def _execute(self, sid, snapshot, context, *, resume, config=None, execution_epoch=None):
        from logagent.workflow.graph import GRAPH_REVISION
        ctx = context or CollectionContext(snapshot.workflow.id, sid, self.log_path, self.credentials, self.session_view)
        config = config or {"configurable": {"thread_id": sid}}
        graph = self._graph(snapshot, ctx)
        state = {"session_id": sid, "snapshot": snapshot.model_dump(mode="json"),
                 "log_path": ctx.log_path, "graph_revision": GRAPH_REVISION,
                 "execution_epoch": execution_epoch, "stopped": False, "status": "running",
                 "degraded": False, "error": None, "phase": {}, "shared_input": "",
                 "analysis_items": {}, "outputs": {}, "intents": {}, "deliveries": {}, "stage_origins": {}}
        try:
            await self.archive.reconcile(sid)
            if resume:
                saved = await graph.aget_state(config, subgraphs=True)
                state = saved.values
                if saved.next:
                    record = await self.get_session(sid)
                    await self._event(sid, f"resumed:{record.version}", record.stage, "running",
                                      execution_epoch=state["execution_epoch"])
                if not saved.next:
                    return await self._settled_result(sid, snapshot, state)
            await self.archive.consume(sid, graph, None if resume else state, config)
            saved = await graph.aget_state({"configurable": {"thread_id": sid}})
            return await self._settled_result(sid, snapshot, saved.values)
        except asyncio.CancelledError:
            await self.archive.reconcile(sid)
            saved = await graph.aget_state({"configurable": {"thread_id": sid}})
            result = await self._result(sid, snapshot, saved.values or state)
            result.status, result.cancelled = "cancelled", True
            record = await self.get_session(sid)
            await self._event(sid, f"cancelled:{record.version}", result.stage, "cancelled", execution_epoch=result_epoch(saved.values or state))
            return result
        except Exception as exc:
            error = exc.info if isinstance(exc, LogAgentError) else exception_error(exc, code="workflow_failed", message="Workflow 执行或归档失败")
            try:
                record = await self.get_session(sid)
                await self._event(sid, f"interrupted:{record.version}", record.stage, "interrupted", error, execution_epoch=state.get("execution_epoch"))
            except Exception:
                logger.exception("Unable to persist interrupted session", extra={"session_id": sid})
            raise LogAgentError(error.code, error.message, error.details) from exc
        finally:
            # Enqueue before returning; the worker waits for this task before checking
            # activity. Backpressure never drops a completed run's maintenance request.
            await self._cleanup.request(sid, completion=asyncio.current_task())

    def _graph(self, snapshot, ctx, *, registry=None):
        from logagent.workflow.graph import build_workflow
        return build_workflow(snapshot=snapshot, context=ctx, checkpointer=self._checkpointer,
            collector_manager=self.collector_manager, ai_service=self.ai_service,
            channel_manager=self.channel_manager, registry=registry)

    async def _settled_result(self, sid, snapshot, state):
        record = await self.get_session(sid)
        status = state.get("status", "running")
        if record.status in {"cancelled", "interrupted", "running"} and status in {"completed", "partial", "failed"}:
            await self._event(sid, f"settled:{record.version}", "finish", status,
                              execution_epoch=state["execution_epoch"])
        return await self._result(sid, snapshot, state)

    async def _result(self, sid, snapshot, state):
        record = await self.get_session(sid)
        result = WorkflowResult(session_id=sid, workflow_id=snapshot.workflow.id,
                                stage=state.get("phase", {}).get("stage", "collect"),
                                status=state.get("status", "running"), stopped=state.get("stopped", False))
        for stage in _STAGES:
            content = await self.session_view.get_phase_content(sid, stage, version=record.version)
            if content.content:
                body = content.content
                for key in ("collection", "analyses", "aggregate", "outputs", "deliveries"):
                    if key in body:
                        result = WorkflowResult.model_validate({**result.model_dump(mode="json"), key: body[key]})
        from logagent.workflow.result import collection_input
        result.shared_input = collection_input(snapshot.workflow, [item.model_dump(mode="json") for item in result.collection])
        if state.get("error"):
            result.errors = [ErrorInfo.model_validate(state["error"])]
        if record.error and record.error.code == "backup_failed":
            result.errors.append(record.error)
            if result.status == "completed":
                result.status = "partial"
        result.notifications = [Notification(session_id=sid, output_id=oid, title=snapshot.workflow.name or snapshot.workflow.id, text=text) for oid, text in result.outputs.items()]
        return result


def result_epoch(state):
    return state.get("execution_epoch")
