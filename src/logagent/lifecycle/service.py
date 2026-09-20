"""协调应用装配、重载、健康准入与分步限时清理，持有各组件的生命周期。"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from logagent.ai import AIService, ChannelFactory, OpenAIChannelFactory
from logagent.channel import ChannelManager, builtin_channels
from logagent.collection import CollectorManager, builtin_collectors
from logagent.config import (
    ConfigurationReader,
    CredentialManager,
    PluginRegistry,
    ResourceStore,
)
from logagent.errors import LogAgentError
from logagent.lifecycle.logging import JsonLogSink
from logagent.models import (
    DiscoveryReport,
    ErrorInfo,
    HealthReport,
    SystemConfig,
)
from logagent.workflow import IntervalTrigger, SessionStore, SessionView, WorkflowService

from .defaults import starter_resources
from .health import capability_diagnostics, component_health, health_components, plugin_health
from .resources import LifecycleResourceStore, effective_config, resource_validators
from .services import ApplicationServices

logger = logging.getLogger("logagent.lifecycle")

_CLEANUP_TIMEOUT = 10.0
_SHUTDOWN_TIMEOUT = 30.0
ReloadScope = Literal["resources", "plugins"]
CheckpointerContextFactory = Callable[[str], Any]


class ApplicationLifecycle:
    """管理单进程应用的资源所有权与运行准入。

    启动、重载和关闭通过同一把锁串行执行；健康检查独立运行并调整准入。
    对外异步入口复用内部任务，调用方取消等待不会取消已开始的生命周期操作。
    """

    def __init__(
        self,
        config: SystemConfig,
        *,
        channel_factories: Mapping[str, ChannelFactory] | None = None,
        clock: Callable[[], float] = time.monotonic,
        shutdown_timeout: float = _SHUTDOWN_TIMEOUT,
        checkpointer_context_factory: CheckpointerContextFactory | None = None,
    ) -> None:
        """规范化配置并初始化所有权记录，资源由 start 创建。

        shutdown_timeout 是暂停准入、停止调度和关闭 Workflow 各步骤的秒数预算，
        不是整个关闭过程的时限；其余组件使用 _CLEANUP_TIMEOUT。
        channel_factories 为 None 时启动默认 HTTP 工厂，显式空映射保持为空。
        """
        if not math.isfinite(shutdown_timeout) or shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be positive and finite")
        self.config = effective_config(config)
        self._channel_factories = channel_factories
        self._clock = clock
        self._shutdown_timeout = shutdown_timeout
        self._checkpointer_context_factory = (
            checkpointer_context_factory or AsyncSqliteSaver.from_conn_string
        )
        self._lifecycle_lock = asyncio.Lock()
        self._start_task: asyncio.Task[ApplicationServices] | None = None
        self._shutdown_task: asyncio.Task[None] | None = None
        self._reload_tasks: dict[ReloadScope, asyncio.Task[Any]] = {}
        self._cleanup_tasks: dict[str, asyncio.Task[Any]] = {}
        self._services: ApplicationServices | None = None
        self._resources: ResourceStore | None = None
        self._log_sink: JsonLogSink | None = None
        self._session_store: SessionStore | None = None
        self._checkpointer_context: Any = None
        self._ai: AIService | None = None
        self._channels: ChannelManager | None = None
        self._workflow: WorkflowService | None = None
        self._intervals: IntervalTrigger | None = None
        self._plugin_report = DiscoveryReport()
        self._reload_diagnostic: ErrorInfo | None = None
        self._reload_in_progress = False
        self._reload_requires_recovery = False
        self._shutdown_requested = False
        self._shutdown_complete = False
        self.failure: ErrorInfo | None = None

    @classmethod
    async def from_file(
        cls,
        location: str | Path,
        *,
        channel_factories: Mapping[str, ChannelFactory] | None = None,
        clock: Callable[[], float] = time.monotonic,
        shutdown_timeout: float = _SHUTDOWN_TIMEOUT,
        checkpointer_context_factory: CheckpointerContextFactory | None = None,
    ) -> ApplicationLifecycle:
        """读取系统配置并构造尚未启动的实例，保留调用方注入的依赖。"""
        config = await ConfigurationReader().load_system(location)
        return cls(
            config,
            channel_factories=channel_factories,
            clock=clock,
            shutdown_timeout=shutdown_timeout,
            checkpointer_context_factory=checkpointer_context_factory,
        )

    @property
    def services(self) -> ApplicationServices:
        """返回已发布的服务容器；容器尚不存在时抛出 not_ready。"""
        if self._services is None:
            raise LogAgentError("not_ready", "应用尚未完成启动")
        return self._services

    @property
    def plugin_report(self) -> DiscoveryReport:
        """返回插件发现报告的深拷贝，避免外部修改内部诊断。"""
        return self._plugin_report.model_copy(deep=True)

    async def start(self) -> ApplicationServices:
        """共享一次启动并返回服务容器，已收到关闭请求的实例不能重新启动。

        调用方取消仅结束自身等待；内部启动继续执行并负责失败清理。
        """
        if self._services is not None and not self._shutdown_requested:
            return self._services
        if self._shutdown_requested:
            raise LogAgentError("shutdown", "应用生命周期已经关闭")

        task = self._start_task
        if task is None or task.done():
            task = asyncio.create_task(self._start_once(), name="lifecycle:start")
            self._start_task = task
            task.add_done_callback(self._consume_task_exception)
        return await asyncio.shield(task)

    async def _start_once(self) -> ApplicationServices:
        """在生命周期锁内按依赖顺序装配，整理中断会话后开放准入。

        逐步记录取得的资源，启动失败时复用关闭流程清理，并保留失败阶段诊断。
        装配本身不执行采集、消息发送或模型调用。
        """
        async with self._lifecycle_lock:
            if self._shutdown_requested:
                raise LogAgentError("shutdown", "应用生命周期已经关闭")
            if self._services is not None:
                return self._services
            if self.failure is not None:
                raise LogAgentError(self.failure.code, self.failure.message, self.failure.details)

            stage = "logging"
            try:
                if self.config.log_file is not None:
                    sink = JsonLogSink(self.config.log_file)
                    self._log_sink = sink
                    sink.start()

                stage = "session_store"
                database = str(Path(self.config.data_dir) / "workflows.sqlite3")
                session_store = SessionStore(database)
                self._session_store = session_store

                stage = "checkpointer"
                context = self._checkpointer_context_factory(database)
                checkpointer = await context.__aenter__()
                self._checkpointer_context = context
                await checkpointer.setup()

                stage = "plugins"
                plugins = PluginRegistry(builtin_collectors(), builtin_channels=builtin_channels())
                self._plugin_report = await plugins.discover_plugins(self.config)
                credentials = CredentialManager(
                    self.config, resources_path=Path(self.config.data_dir) / "resources.json"
                )
                collectors = CollectorManager(plugins.collectorRegister)

                stage = "ai"
                ai = AIService(
                    channel_factories=self._channel_factories
                    if self._channel_factories is not None
                    else {
                        "http": OpenAIChannelFactory(),
                    },
                    credential_resolver=credentials,
                )
                self._ai = ai

                stage = "channels"
                channels = ChannelManager(
                    plugins.channelRegister,
                    credentials=credentials,
                )
                self._channels = channels

                stage = "resources"
                resources = LifecycleResourceStore(
                    Path(self.config.data_dir) / "resources.json",
                    collector_register=plugins.collectorRegister,
                    channel_register=plugins.channelRegister,
                    validators=resource_validators(
                        plugins.collectorRegister,
                        plugins.channelRegister,
                        collectors,
                        channels,
                        ai,
                    ),
                    data_dir=self.config.data_dir,
                    initial_resources=starter_resources(),
                    on_change=self._resource_view_changed,
                )
                self._resources = resources

                stage = "workflow"
                session_view = SessionView(session_store)
                workflow = WorkflowService(
                    collectors,
                    ai,
                    channels,
                    resources,
                    session_store=session_store,
                    session_view=session_view,
                    checkpointer=checkpointer,
                    max_concurrent_runs=self.config.max_concurrent_runs,
                    credentials=credentials,
                    log_path=self.config.log_file,
                )
                self._workflow = workflow
                await workflow.pause_admission()
                await workflow.reconcile_interrupted()

                stage = "intervals"
                intervals = IntervalTrigger(workflow, clock=self._clock)
                self._intervals = intervals
                intervals.update(resources.list("workflows"))

                if self._shutdown_requested:
                    raise LogAgentError("shutdown", "应用启动期间收到关闭请求")

                services = ApplicationServices(
                    system_config=self.config,
                    credentials=credentials,
                    plugins=plugins,
                    resources=resources,
                    session_store=session_store,
                    session_view=session_view,
                    checkpointer=checkpointer,
                    collectors=collectors,
                    ai=ai,
                    channels=channels,
                    workflow=workflow,
                    intervals=intervals,
                    log_path=self.config.log_file,
                )
                self._services = services
                intervals.start()
                if self._shutdown_requested:
                    raise LogAgentError("shutdown", "应用启动期间收到关闭请求")
                workflow.resume_admission()
                logger.info(
                    "application_started",
                    extra={
                        "event": "application_started",
                        "active_runs": workflow.coordinator.active,
                    },
                )
                return services
            except asyncio.CancelledError:
                await self._cleanup_startup()
                raise
            except Exception as exc:
                details: dict[str, Any] = {
                    "stage": stage,
                    "exception_type": type(exc).__name__,
                }
                if isinstance(exc, LogAgentError):
                    details["reason"] = exc.code
                failure = ErrorInfo(
                    code="lifecycle_start_failed",
                    message="应用启动失败",
                    details=details,
                )
                logger.error(
                    "application_start_failed",
                    extra={
                        "event": "application_start_failed",
                        "error_code": failure.code,
                        "stage": stage,
                    },
                )
                cleanup_errors = await self._cleanup_startup()
                if cleanup_errors:
                    failure.details = {**failure.details, "cleanup_errors": cleanup_errors}
                if not self._shutdown_requested:
                    self.failure = failure
                raise LogAgentError(failure.code, failure.message, failure.details) from None

    async def reload(self, scope: ReloadScope = "resources") -> DiscoveryReport | None:
        """共享同一 scope 的在途重载，调用方取消不会中断内部发布。

        resources 重新读取资源并更新后续调度，返回 None；plugins 更新插件依赖，
        返回发现报告。插件重载的冲突、恢复要求由内部操作处理。
        """
        if scope not in ("resources", "plugins"):
            raise LogAgentError("invalid_argument", "reload scope 必须为 resources 或 plugins")
        if self._shutdown_requested:
            raise LogAgentError("shutdown", "应用已经关闭")

        task = self._reload_tasks.get(scope)
        if task is None or task.done():
            task = asyncio.create_task(self._reload_once(scope), name=f"lifecycle:reload:{scope}")
            self._reload_tasks[scope] = task
            task.add_done_callback(self._consume_task_exception)
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._reload_tasks.pop(scope, None)

    async def _reload_once(self, scope: ReloadScope) -> DiscoveryReport | None:
        """串行化重载与启动、关闭；资源文件读取移至工作线程。"""
        async with self._lifecycle_lock:
            if self._shutdown_requested:
                raise LogAgentError("shutdown", "应用已经关闭")
            services = self.services
            if scope == "resources":
                await asyncio.to_thread(services.resources.reload_resources)
                self._resource_view_changed()
                logger.info(
                    "resources_reloaded",
                    extra={"event": "resources_reloaded", "scope": "resources"},
                )
                return None
            return await self._reload_plugins(services)

    async def _reload_plugins(self, services: ApplicationServices) -> DiscoveryReport:
        """暂停调度和准入，在没有活动运行时替换插件及其依赖。

        活动运行冲突时恢复原准入与调度状态，关闭请求优先。
        其他失败或内部任务取消会保留恢复标记，阻止健康检查重新开放准入；
        只有后续插件重载成功才清除标记。单个插件发现错误可作为降级报告返回。
        """
        old_channels = services.plugins.channelRegister
        old_owners = sorted(
            {item.plugin for item in old_channels.describe() if item.plugin != "builtin"}
        )
        was_accepting = services.workflow.coordinator.accepting
        paused_before = services.intervals.paused
        self._reload_in_progress = True
        services.intervals.paused = True
        stage = "pause_admission"
        try:
            active = await services.workflow.pause_admission()
            if active:
                self._reload_diagnostic = ErrorInfo(
                    code="plugin_reload_conflict",
                    message="存在活动运行时不能 reload 插件",
                    details={"active_runs": active},
                )
                if was_accepting and not self._shutdown_requested:
                    services.workflow.resume_admission()
                if not self._shutdown_requested:
                    services.intervals.paused = paused_before
                raise LogAgentError(
                    "plugin_reload_conflict",
                    "存在活动运行时不能 reload 插件",
                    {"active_runs": active},
                )

            stage = "unload_owners"
            for owner in old_owners:
                await services.channels.unload_owner(owner)

            stage = "discover"
            report = await services.plugins.reload_plugins(self.config)

            stage = "publish_collectors"
            services.collectors.reload_register(services.plugins.collectorRegister)

            stage = "publish_channels"
            await services.channels.reload_register(services.plugins.channelRegister)

            stage = "publish_resources"
            services.resources.update_dependencies(
                collector_register=services.plugins.collectorRegister,
                channel_register=services.plugins.channelRegister,
                validators=resource_validators(
                    services.plugins.collectorRegister,
                    services.plugins.channelRegister,
                    services.collectors,
                    services.channels,
                    services.ai,
                ),
            )
            if self._shutdown_requested:
                raise LogAgentError("shutdown", "插件重载期间收到关闭请求")

            self._plugin_report = report
            self._reload_diagnostic = None
            self._reload_requires_recovery = False
            services.workflow.resume_admission()
            services.intervals.paused = False
            logger.info(
                "plugins_reloaded",
                extra={
                    "event": "plugins_reloaded",
                    "scope": "plugins",
                    "status": "degraded" if report.errors else "available",
                },
            )
            return report
        except asyncio.CancelledError:
            self._reload_requires_recovery = True
            self._reload_diagnostic = ErrorInfo(
                code="plugin_reload_cancelled",
                message="插件重载被取消，准入保持关闭",
                details={"stage": stage},
            )
            raise
        except Exception as exc:
            if isinstance(exc, LogAgentError) and exc.code == "plugin_reload_conflict":
                raise
            self._reload_requires_recovery = True
            code = exc.code if isinstance(exc, LogAgentError) else "plugin_reload_failed"
            self._reload_diagnostic = ErrorInfo(
                code=code,
                message="插件重载失败",
                details={"stage": stage, "exception_type": type(exc).__name__},
            )
            logger.error(
                "plugin_reload_failed",
                extra={
                    "event": "plugin_reload_failed",
                    "scope": "plugins",
                    "error_code": code,
                    "stage": stage,
                },
            )
            raise
        finally:
            self._reload_in_progress = False

    async def health(self) -> HealthReport:
        """执行本地探测并据必需组件状态调整新运行准入，返回健康报告。

        此方法不持有生命周期锁，也不取消活动会话；探测后读取最新重载状态，
        以免覆盖关闭、重载进行中或等待显式恢复时的准入限制。
        """
        now = datetime.now(UTC)
        services = self._services
        if services is None:
            error = self.failure or ErrorInfo(code="not_started", message="应用尚未启动")
            return HealthReport(
                status="unavailable",
                accepting_runs=False,
                checked_at=now,
                components=[component_health("lifecycle", now, error)],
            )

        diagnostics = capability_diagnostics(services)
        components = await health_components(services, self._log_sink, now)
        plugins = plugin_health(self._plugin_report, diagnostics, self._reload_diagnostic, now)
        components.append(plugins)
        required_healthy = all(
            component.status == "available" for component in components if component.required
        )
        allowed = (
            not self._shutdown_requested
            and not self._reload_in_progress
            and not self._reload_requires_recovery
            and required_healthy
        )
        if not allowed and services.workflow.coordinator.accepting:
            await services.workflow.pause_admission()
        elif allowed and not services.workflow.coordinator.accepting:
            services.workflow.resume_admission()
        accepting = allowed and services.workflow.coordinator.accepting
        status = "unavailable" if not accepting else ("degraded" if plugins.error else "ready")
        return HealthReport(
            status=status,
            accepting_runs=accepting,
            checked_at=now,
            components=components,
        )

    async def shutdown(self) -> None:
        """记录关闭意图并暂停定时触发，共享可重试的内部清理任务。

        准入关闭由清理流程调用 Workflow.pause_admission，与 trigger 使用同一把锁，
        避免直接改标记打断已通过首次检查但尚未提交的触发。调用方取消不终止清理，
        完全关闭后重复调用无副作用。
        """
        self._shutdown_requested = True
        services = self._services
        if services is not None:
            services.intervals.paused = True
        if self._shutdown_complete:
            return
        task = self._shutdown_task
        if task is None or task.done():
            task = asyncio.create_task(self._shutdown_once(), name="lifecycle:shutdown")
            self._shutdown_task = task
            task.add_done_callback(self._consume_task_exception)
        await asyncio.shield(task)

    async def _shutdown_once(self) -> None:
        """持锁执行清理；未完成时以 lifecycle_shutdown_failed 暴露逐步诊断。"""
        async with self._lifecycle_lock:
            if self._shutdown_complete:
                return
            errors: list[dict[str, Any]] = []
            if not await self._cleanup_owned(errors, emit_stopped=True):
                raise LogAgentError(
                    "lifecycle_shutdown_failed",
                    "应用关闭时存在清理失败",
                    {"errors": errors},
                )
            self._shutdown_complete = True

    async def _cleanup_startup(self) -> list[dict[str, Any]]:
        """清理启动已取得的资源并撤下服务容器，返回诊断供原始失败附带。"""
        errors: list[dict[str, Any]] = []
        await self._cleanup_owned(errors, emit_stopped=False)
        self._services = None
        return errors

    async def _cleanup_owned(self, errors: list[dict[str, Any]], *, emit_stopped: bool) -> bool:
        """先停准入与运行，再释放 AI、通道、存储，最后关闭日志。

        任一步失败或超时即停止后续清理并向 errors 追加诊断，保留仍被依赖的资源。
        只有成功释放的组件才清空所有权引用；全部完成返回 True。
        """
        if self._intervals is not None and self._workflow is not None:
            if not await self._cleanup(
                "workflow_pause_admission",
                self._workflow.pause_admission,
                errors,
                self._shutdown_timeout,
            ):
                return False

        if self._intervals is not None:
            if not await self._cleanup(
                "intervals", self._intervals.stop, errors, self._shutdown_timeout
            ):
                return False
            self._intervals = None

        if self._workflow is not None:
            if not await self._cleanup(
                "workflow", self._workflow.shutdown, errors, self._shutdown_timeout
            ):
                return False
            self._workflow = None

        if self._ai is not None:
            if not await self._cleanup("ai", self._ai.close, errors, _CLEANUP_TIMEOUT):
                return False
            self._ai = None

        if self._channels is not None:
            if not await self._cleanup("channels", self._channels.stop, errors, _CLEANUP_TIMEOUT):
                return False
            self._channels = None

        if self._checkpointer_context is not None:
            context = self._checkpointer_context

            async def close_checkpointer() -> None:
                """通过创建时的异步上下文释放 checkpointer。"""
                await context.__aexit__(None, None, None)

            if not await self._cleanup(
                "checkpointer", close_checkpointer, errors, _CLEANUP_TIMEOUT
            ):
                return False
            self._checkpointer_context = None

        if self._session_store is not None:
            store = self._session_store
            if not await self._cleanup(
                "session_store",
                lambda: asyncio.to_thread(store.close),
                errors,
                _CLEANUP_TIMEOUT,
            ):
                return False
            self._session_store = None

        if emit_stopped and self._log_sink is not None:
            logger.info(
                "application_stopped",
                extra={
                    "event": "application_stopped",
                    "status": "failed" if errors else "completed",
                },
            )
        if self._log_sink is not None:
            if not await self._cleanup(
                "logging",
                self._close_sink,
                errors,
                _CLEANUP_TIMEOUT,
            ):
                return False
            self._log_sink = None

        self._services = None
        self._resources = None
        return True

    async def _close_sink(self) -> None:
        """将日志 sink 的同步关闭接入统一的异步清理接口。"""
        sink = self._log_sink
        if sink is not None:
            sink.close()

    async def _cleanup(
        self,
        name: str,
        operation: Callable[[], Awaitable[Any]],
        errors: list[dict[str, Any]],
        budget: float,
    ) -> bool:
        """在 budget 秒内等待具名清理任务，将失败诊断追加到 errors。

        超时不取消任务，下次调用继续等待同一任务；已结束的失败任务则允许重建。
        外部取消等待同样不取消实际清理，避免提前释放仍在使用的下游依赖。
        """
        task = self._cleanup_tasks.get(name)
        if task is None:
            task = asyncio.create_task(operation(), name=f"lifecycle:cleanup:{name}")
            self._cleanup_tasks[name] = task
            task.add_done_callback(self._consume_task_exception)
        done, _ = await asyncio.shield(asyncio.wait({task}, timeout=budget))
        if task not in done:
            errors.append(
                {
                    "component": name,
                    "code": "cleanup_timeout",
                    "timeout_seconds": budget,
                }
            )
            return False
        self._cleanup_tasks.pop(name, None)
        try:
            task.result()
            return True
        except asyncio.CancelledError:
            errors.append({"component": name, "exception_type": "CancelledError"})
            return False
        except Exception as exc:
            errors.append({"component": name, "exception_type": type(exc).__name__})
            return False

    @staticmethod
    def _consume_task_exception(task: asyncio.Task[Any]) -> None:
        """提取无人等待的任务异常以免产生警告；后续 await 仍会抛出该异常。"""
        if not task.cancelled():
            task.exception()

    def _resource_view_changed(self) -> None:
        """依据最新资源重建未来的定时计划；关闭意图出现后停止刷新。"""
        if (
            not self._shutdown_requested
            and self._resources is not None
            and self._intervals is not None
        ):
            self._intervals.update(self._resources.list("workflows"))
