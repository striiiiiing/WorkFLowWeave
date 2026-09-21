"""Workflow 运行编排：固定快照、执行阶段图、记录业务事实并恢复原运行。

LangGraph checkpoint 管理控制进度，SessionStore 保存独立可读的业务存档；
两者通过稳定引用衔接，不假设跨存储事务。阅读顺序可从 trigger、_execute、
_graph 进入各阶段，再检查 recover 与通知意图/回执的恢复边界。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field, TypeAdapter

from logagent.errors import LogAgentError, exception_error
from logagent.models import (
    ID,
    AnalysisResult,
    CollectionContext,
    CollectionResult,
    DeliveryResult,
    ErrorInfo,
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
    """一次运行的业务结果，按阶段存档逐步组装。

    collection、analyses 保持定义顺序；outputs 是通知使用的冻结输出。
    stopped 表示不再进入下游业务阶段，并不必然表示失败，例如全空跳过。
    """
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
        """返回采集结果列表，作为 collection 字段的访问别名。"""
        return self.collection

    @property
    def analysis_results(self):
        """返回分析结果列表，作为 analyses 字段的访问别名。"""
        return self.analyses



async def _call(fn: Callable, *args, **kwargs):
    """调用注入的同步或异步接口，统一返回实际结果。"""
    value = fn(*args, **kwargs)
    return await value if inspect.isawaitable(value) else value



def _archive_references(value):
    """递归提取 checkpoint 或待提交写入中的 items、phases 存档引用。"""
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
        self._shutdown = False
        self._shutdown_task: asyncio.Task | None = None

    async def start(self):
        """串行初始化自有 checkpointer；初始化失败释放上下文并继续抛错。"""
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
            runtime = ArchiveRuntime(self.session_store, sid, snapshot.workflow.backup)
            await asyncio.to_thread(
                self.session_store.create,
                sid,
                snapshot.workflow.id,
                runtime.policy,
                workflow_name=snapshot.workflow.name,
            )
            ctx = context or CollectionContext(
                snapshot.workflow.id, sid, self.log_path, self.credentials, self.session_view
            )
            await self._snapshot_node(runtime, snapshot, ctx)({})
            self.coordinator.submit(sid, lambda: self._execute(sid, snapshot, ctx, resume=False))
        return sid

    async def _recovery_material(self, session_id):
        """One material check shared by eligibility queries and actual recovery."""
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
        return snapshot, entry["body"].get("log_path")

    async def recovery_availability(self, session_id):
        """Read current recovery eligibility without submitting or modifying a run."""
        from logagent.models import RecoveryAvailability

        _ID.validate_python(session_id)
        await self.start()
        await self.session_view.get_session(session_id)
        async with self._admission_lock:
            try:
                self.coordinator.check(session_id)
                await self._recovery_material(session_id)
            except LogAgentError as exc:
                return RecoveryAvailability(available=False, reason=exc.info)
        return RecoveryAvailability(available=True)

    async def recover(self, session_id, *, context=None):
        """验证恢复材料后，在原 session 对应的 LangGraph thread 上继续运行。

        必须具备原 checkpoint、快照和引用条目；输出冻结后要求冻结正文可用，
        否则检查已存采集及分析正文。缺失材料时报错，不通过重新采集补齐。
        恢复沿用原日志路径，提交后返回原 session_id。
        """
        _ID.validate_python(session_id)
        await self.start()
        async with self._admission_lock:
            self.coordinator.check(session_id)
            snapshot, saved_path = await self._recovery_material(session_id)
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
        if self._saver_context is not None:
            await self._saver_context.__aexit__(None, None, None)
            self._saver_context = None
        if self._owns_store:
            await asyncio.to_thread(self.session_store.close)

    async def _event(self, runtime, key, stage, status, error=None):
        """复用存档节点写入具有稳定事件键的状态或错误管理记录。"""
        async def value(state):
            """生成事件正文，将业务错误转换为可序列化数据。"""
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

    async def _final_result(self, runtime, snapshot, state):
        """读取最终结果，并在终态存档与可读状态不一致时追加收敛事件。"""
        result = await self._result(runtime, snapshot, state)
        record = await self.get_session(runtime.session_id)
        if result.status in {"completed", "partial", "failed"} and record.status != result.status:
            await self._event(runtime, f"settled:{record.version}", result.stage, result.status)
        return result


    async def _execute(self, sid, snapshot, context, *, resume):
        """执行首次运行或恢复，并记录运行、取消和中断事件。

        恢复已结束的失败图时，依据原 checkpoint 的 retry_stage 开启新代次；
        已结束且无重试边界的图直接返回结果。图调用使用同步持久化边界。
        取消返回 cancelled 结果；执行或存档异常记录 interrupted 后抛出错误。
        """
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


    def _graph(self, runtime, snapshot, ctx):
        """创建本次运行的 LangGraph；图节点实现位于 workflow.graph。"""
        from logagent.workflow.graph import WorkflowGraph

        return WorkflowGraph(
            runtime=runtime, snapshot=snapshot, context=ctx,
            checkpointer=self._checkpointer,
            collector_manager=self.collector_manager,
            ai_service=self.ai_service, channel_manager=self.channel_manager,
        ).compile()

    def _snapshot_node(self, runtime, snapshot, ctx):
        """返回快照存档节点；快照节点与执行图共用图组件。"""
        from logagent.workflow.graph import WorkflowGraph

        return WorkflowGraph(
            runtime=runtime, snapshot=snapshot, context=ctx,
            checkpointer=self._checkpointer,
            collector_manager=self.collector_manager,
            ai_service=self.ai_service, channel_manager=self.channel_manager,
        ).snapshot_node()

    async def _result(self, runtime, snapshot, state, *, required=()):
        """从图组件读取阶段存档并组装对外结果。"""
        from logagent.workflow.graph import WorkflowGraph

        return await WorkflowGraph(
            runtime=runtime, snapshot=snapshot, context=None,
            checkpointer=self._checkpointer,
            collector_manager=self.collector_manager,
            ai_service=self.ai_service, channel_manager=self.channel_manager,
        ).result(state, required=required)
