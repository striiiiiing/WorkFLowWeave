"""Application assembly, reload coordination, health and bounded shutdown."""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import ValidationError

from logagent.ai import AIService, ModelFactory, OpenAIModelFactory
from logagent.channel import ChannelManager, builtin_channels
from logagent.collection import CollectorManager, builtin_collectors
from logagent.config import (
    ConfigurationReader,
    CredentialManager,
    PluginRegistry,
    ResourceStore,
)
from logagent.errors import LogAgentError, validation_error
from logagent.lifecycle.logging import JsonLogSink
from logagent.models import (
    AIConfig,
    ChannelConfig,
    ComponentHealth,
    DiscoveryReport,
    ErrorInfo,
    HealthReport,
    SourceConfig,
    StrictModel,
    SystemConfig,
    copy_model,
)
from logagent.protocols import ChannelRegistryView, CollectorRegistryView
from logagent.workflow import IntervalTrigger, SessionStore, SessionView, WorkflowService

logger = logging.getLogger("logagent.lifecycle")

_CLEANUP_TIMEOUT = 10.0
_SHUTDOWN_TIMEOUT = 30.0
ReloadScope = Literal["resources", "plugins"]
CheckpointerContextFactory = Callable[[str], Any]


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    """Concrete, already-assembled services for Interaction to inject."""

    system_config: SystemConfig
    credentials: CredentialManager
    plugins: PluginRegistry
    resources: ResourceStore
    session_store: SessionStore
    session_view: SessionView
    checkpointer: Any
    collectors: CollectorManager
    ai: AIService
    channels: ChannelManager
    workflow: WorkflowService
    intervals: IntervalTrigger
    log_path: str | None


class _LifecycleResourceStore(ResourceStore):
    """Resource store that rebuilds interval plans after an atomic publish."""

    def __init__(self, *args: Any, on_change: Callable[[], None], **kwargs: Any) -> None:
        self._on_change = on_change
        self._loop = asyncio.get_running_loop()
        super().__init__(*args, **kwargs)

    def _published(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is self._loop:
            self._on_change()
        else:
            self._loop.call_soon_threadsafe(self._on_change)

    def save(self, kind: str, resource: Any, *, mode: str = "upsert") -> StrictModel:
        value = super().save(kind, resource, mode=mode)
        self._published()
        return value

    def delete(self, kind: str, ident: str) -> None:
        super().delete(kind, ident)
        self._published()


class ApplicationLifecycle:
    """Own startup, reload, health and shutdown for one single-process application."""

    def __init__(
        self,
        config: SystemConfig,
        *,
        model_factories: Mapping[str, ModelFactory] | None = None,
        clock: Callable[[], float] = time.monotonic,
        shutdown_timeout: float = _SHUTDOWN_TIMEOUT,
        checkpointer_context_factory: CheckpointerContextFactory | None = None,
    ) -> None:
        if not math.isfinite(shutdown_timeout) or shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be positive and finite")
        self.config = self._effective_config(config)
        self._model_factories = model_factories
        self._clock = clock
        self._shutdown_timeout = shutdown_timeout
        self._checkpointer_context_factory = (
            checkpointer_context_factory or AsyncSqliteSaver.from_conn_string
        )
        self._lifecycle_lock = asyncio.Lock()
        self._start_task: asyncio.Task[ApplicationServices] | None = None
        self._shutdown_task: asyncio.Task[None] | None = None
        self._reload_tasks: dict[ReloadScope, asyncio.Task[Any]] = {}
        self._cleanup_tasks: dict[str, asyncio.Task[None]] = {}
        self._services: ApplicationServices | None = None
        self._resources: ResourceStore | None = None
        self._log_sink: JsonLogSink | None = None
        self._session_store: SessionStore | None = None
        self._checkpointer_context: Any = None
        self._checkpointer: Any = None
        self._ai: AIService | None = None
        self._channels: ChannelManager | None = None
        self._workflow: WorkflowService | None = None
        self._intervals: IntervalTrigger | None = None
        self._plugin_report = DiscoveryReport()
        self._reload_diagnostic: ErrorInfo | None = None
        self._reload_in_progress = False
        self._reload_requires_recovery = False
        self._started = False
        self._shutdown_requested = False
        self._shutdown = False
        self._shutdown_complete = False
        self.failure: ErrorInfo | None = None

    @classmethod
    async def from_file(
        cls,
        location: str | Path,
        *,
        model_factories: Mapping[str, ModelFactory] | None = None,
        clock: Callable[[], float] = time.monotonic,
        shutdown_timeout: float = _SHUTDOWN_TIMEOUT,
        checkpointer_context_factory: CheckpointerContextFactory | None = None,
    ) -> ApplicationLifecycle:
        config = await ConfigurationReader().load_system(location)
        return cls(
            config,
            model_factories=model_factories,
            clock=clock,
            shutdown_timeout=shutdown_timeout,
            checkpointer_context_factory=checkpointer_context_factory,
        )

    @staticmethod
    def _effective_config(config: SystemConfig) -> SystemConfig:
        try:
            result = copy_model(config)
        except ValidationError as exc:
            raise validation_error(exc) from None
        base = Path.cwd()

        def resolved(value: str) -> str:
            try:
                path = Path(value)
                return str((path if path.is_absolute() else base / path).resolve())
            except (OSError, ValueError, RuntimeError):
                raise LogAgentError("invalid_config", "系统路径无法解析") from None

        result.data_dir = resolved(result.data_dir)
        result.plugin_dir = resolved(result.plugin_dir)
        result.log_file = resolved(result.log_file) if result.log_file is not None else None
        return result

    @property
    def services(self) -> ApplicationServices:
        if self._services is None:
            raise LogAgentError("not_ready", "应用尚未完成启动")
        return self._services

    @property
    def plugin_report(self) -> DiscoveryReport:
        return self._plugin_report.model_copy(deep=True)

    def _validators(
        self,
        collector_register: CollectorRegistryView,
        channel_register: ChannelRegistryView,
        collectors: CollectorManager,
        channels: ChannelManager,
        ai: AIService,
    ) -> dict[str, Callable[[StrictModel], None]]:
        def source_validator(value: StrictModel) -> None:
            source = SourceConfig.model_validate(value)
            if collector_register.get(source.collector) is not None:
                collectors.validate(source)

        def channel_validator(value: StrictModel) -> None:
            channel = ChannelConfig.model_validate(value)
            if channel_register.get(channel.channel) is not None:
                channels.validate(channel)

        def ai_validator(value: StrictModel) -> None:
            ai.validate(AIConfig.model_validate(value))

        return {
            "sources": source_validator,
            "channels": channel_validator,
            "ai": ai_validator,
        }

    async def start(self) -> ApplicationServices:
        if self._services is not None and self._started and not self._shutdown_requested:
            return self._services
        if self._shutdown_requested or self._shutdown:
            raise LogAgentError("shutdown", "应用生命周期已经关闭")

        task = self._start_task
        if task is None or task.done():
            task = asyncio.create_task(self._start_once(), name="lifecycle:start")
            self._start_task = task
            task.add_done_callback(self._consume_task_exception)
        return await asyncio.shield(task)

    async def _start_once(self) -> ApplicationServices:
        async with self._lifecycle_lock:
            if self._shutdown_requested:
                raise LogAgentError("shutdown", "应用生命周期已经关闭")
            if self._services is not None and self._started:
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
                self._checkpointer_context, self._checkpointer = context, checkpointer
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
                    model_factories=self._model_factories if self._model_factories is not None else {
                        "http": OpenAIModelFactory(),
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
                resources = _LifecycleResourceStore(
                    Path(self.config.data_dir) / "resources.json",
                    collector_register=plugins.collectorRegister,
                    channel_register=plugins.channelRegister,
                    validators=self._validators(
                        plugins.collectorRegister,
                        plugins.channelRegister,
                        collectors,
                        channels,
                        ai,
                    ),
                    data_dir=self.config.data_dir,
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
                self._started = True
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
        if scope not in ("resources", "plugins"):
            raise LogAgentError("invalid_argument", "reload scope 必须为 resources 或 plugins")
        if self._shutdown_requested or self._shutdown:
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
                validators=self._validators(
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
        except LogAgentError as exc:
            if exc.code != "plugin_reload_conflict":
                self._reload_requires_recovery = True
                self._reload_diagnostic = ErrorInfo(
                    code=exc.code,
                    message="插件重载失败",
                    details={"stage": stage, "exception_type": type(exc).__name__},
                )
                logger.error(
                    "plugin_reload_failed",
                    extra={
                        "event": "plugin_reload_failed",
                        "scope": "plugins",
                        "error_code": exc.code,
                        "stage": stage,
                    },
                )
            raise
        except Exception as exc:
            self._reload_requires_recovery = True
            self._reload_diagnostic = ErrorInfo(
                code="plugin_reload_failed",
                message="插件重载失败",
                details={"stage": stage, "exception_type": type(exc).__name__},
            )
            logger.error(
                "plugin_reload_failed",
                extra={
                    "event": "plugin_reload_failed",
                    "scope": "plugins",
                    "error_code": self._reload_diagnostic.code,
                    "stage": stage,
                },
            )
            raise
        finally:
            self._reload_in_progress = False

    async def health(self) -> HealthReport:
        now = datetime.now(UTC)
        if self._services is None:
            error = self.failure or ErrorInfo(code="not_started", message="应用尚未启动")
            return HealthReport(
                status="unavailable",
                accepting_runs=False,
                checked_at=now,
                components=[
                    ComponentHealth(
                        component="lifecycle",
                        status="unavailable",
                        required=True,
                        error=error,
                        checked_at=now,
                    )
                ],
            )

        services = self._services
        diagnostics = self._capability_diagnostics(services)
        components = await self._health_components(services, now)
        if self._plugin_report.errors or diagnostics or self._reload_diagnostic:
            details = {
                "discovery_errors": [
                    item.model_dump(mode="json") for item in self._plugin_report.errors
                ],
                "capability_errors": [item.model_dump(mode="json") for item in diagnostics],
                "reload_error": (
                    self._reload_diagnostic.model_dump(mode="json")
                    if self._reload_diagnostic
                    else None
                ),
            }
            components.append(
                ComponentHealth(
                    component="plugins",
                    status="degraded",
                    required=False,
                    error=ErrorInfo(
                        code="plugin_degraded",
                        message="可选插件存在诊断",
                        details=details,
                    ),
                    checked_at=now,
                )
            )
        else:
            components.append(
                ComponentHealth(
                    component="plugins",
                    status="available",
                    required=False,
                    checked_at=now,
                )
            )

        required_healthy = all(
            component.status == "available" for component in components if component.required
        )
        allowed = (
            not self._shutdown_requested
            and not self._shutdown
            and not self._reload_in_progress
            and not self._reload_requires_recovery
            and required_healthy
        )
        if not allowed and services.workflow.coordinator.accepting:
            await services.workflow.pause_admission()
        elif allowed and not services.workflow.coordinator.accepting:
            services.workflow.resume_admission()
        accepting = allowed and services.workflow.coordinator.accepting

        status: Literal["ready", "degraded", "unavailable"] = "ready"
        if (
            self._shutdown_requested
            or self._shutdown
            or self._reload_in_progress
            or self._reload_requires_recovery
            or not accepting
        ):
            status = "unavailable"
        elif diagnostics or self._plugin_report.errors or self._reload_diagnostic:
            status = "degraded"
        return HealthReport(
            status=status,
            accepting_runs=accepting,
            checked_at=now,
            components=components,
        )

    async def _health_components(
        self, services: ApplicationServices, checked_at: datetime
    ) -> list[ComponentHealth]:
        return [
            await self._health_component(
                "system_config",
                True,
                checked_at,
                self._required_paths_error,
            ),
            await self._health_component(
                "credentials",
                True,
                checked_at,
                lambda: (
                    None
                    if services.credentials is not None
                    else ErrorInfo(
                        code="component_unavailable",
                        message="凭据管理组件不可用",
                    )
                ),
            ),
            await self._health_component(
                "resource_store",
                True,
                checked_at,
                lambda: self._probe_resource_store(services),
            ),
            await self._health_component(
                "session_store",
                True,
                checked_at,
                lambda: self._probe_session_store(services),
            ),
            await self._health_component(
                "checkpointer",
                True,
                checked_at,
                lambda: self._probe_checkpointer(services),
            ),
            await self._health_component(
                "workflow",
                True,
                checked_at,
                lambda: self._probe_workflow(services),
            ),
            await self._health_component(
                "intervals",
                True,
                checked_at,
                lambda: self._probe_intervals(services),
            ),
            await self._health_component(
                "ai",
                True,
                checked_at,
                lambda: self._probe_ai(services),
            ),
            await self._health_component(
                "channels",
                True,
                checked_at,
                lambda: self._probe_channels(services),
            ),
            await self._health_component(
                "logging",
                self.config.log_file is not None,
                checked_at,
                self._probe_log_sink,
            ),
        ]

    async def _health_component(
        self,
        name: str,
        required: bool,
        checked_at: datetime,
        check: Callable[[], Any],
    ) -> ComponentHealth:
        error: ErrorInfo | None
        try:
            error = check()
            if inspect.isawaitable(error):
                error = await error
        except Exception as exc:
            error = self._component_error(name, exc)
        if error is None:
            return ComponentHealth(
                component=name,
                status="available",
                required=required,
                checked_at=checked_at,
            )
        return ComponentHealth(
            component=name,
            status="unavailable" if required else "degraded",
            required=required,
            error=error,
            checked_at=checked_at,
        )

    def _required_paths_error(self) -> ErrorInfo | None:
        if not self.config.data_dir or not self.config.plugin_dir:
            return ErrorInfo(
                code="component_unavailable",
                message="系统配置缺少必要路径",
            )
        return None

    @staticmethod
    def _probe_resource_store(services: ApplicationServices) -> ErrorInfo | None:
        services.resources.list("workflows")
        return None

    @staticmethod
    async def _probe_session_store(services: ApplicationServices) -> ErrorInfo | None:
        await asyncio.to_thread(services.session_store.session_ids)
        return None

    @staticmethod
    async def _probe_checkpointer(services: ApplicationServices) -> ErrorInfo | None:
        checkpointer = services.checkpointer
        if checkpointer is None or getattr(checkpointer, "is_setup", True) is not True:
            return ErrorInfo(
                code="component_unavailable",
                message="Workflow checkpointer 未就绪",
            )
        check = getattr(checkpointer, "check", None)
        if callable(check):
            result = check()
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, ErrorInfo):
                return result
        aget_tuple = getattr(checkpointer, "aget_tuple", None)
        if callable(aget_tuple):
            await aget_tuple({"configurable": {"thread_id": "__lifecycle_health__"}})
        return None

    @staticmethod
    def _probe_workflow(services: ApplicationServices) -> ErrorInfo | None:
        if getattr(services.workflow, "_shutdown", False):
            return ErrorInfo(
                code="component_unavailable",
                message="Workflow 已关闭",
            )
        return None

    @staticmethod
    def _probe_intervals(services: ApplicationServices) -> ErrorInfo | None:
        task = getattr(services.intervals, "_task", None)
        if task is None or task.done():
            return ErrorInfo(
                code="component_unavailable",
                message="定时触发任务未运行",
            )
        return None

    @staticmethod
    def _probe_ai(services: ApplicationServices) -> ErrorInfo | None:
        if getattr(services.ai, "_close_task", None) is not None:
            return ErrorInfo(
                code="component_unavailable",
                message="AI 服务已关闭",
            )
        return None

    @staticmethod
    def _probe_channels(services: ApplicationServices) -> ErrorInfo | None:
        if getattr(services.channels, "_stopping", False):
            return ErrorInfo(
                code="component_unavailable",
                message="ChannelManager 正在关闭",
            )
        return None

    async def _probe_log_sink(self) -> ErrorInfo | None:
        if self.config.log_file is None:
            return None
        sink = self._log_sink
        if sink is None:
            return ErrorInfo(
                code="component_unavailable",
                message="日志 sink 未初始化",
            )
        check = getattr(sink, "check", None)
        if callable(check):
            result = check()
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, ErrorInfo):
                return result
            if result is False:
                return ErrorInfo(
                    code="component_unavailable",
                    message="日志 sink 本地检查失败",
                )
        error = getattr(sink, "error", None)
        if isinstance(error, ErrorInfo):
            return error
        handler = getattr(sink, "_handler", None)
        if handler is None or getattr(getattr(handler, "stream", None), "closed", False):
            return ErrorInfo(
                code="component_unavailable",
                message="日志 sink 未打开",
            )
        return None

    @staticmethod
    def _component_error(component: str, exc: Exception) -> ErrorInfo:
        details: dict[str, Any] = {
            "component": component,
            "exception_type": type(exc).__name__,
        }
        if isinstance(exc, LogAgentError):
            details["reason"] = exc.code
        return ErrorInfo(
            code="component_check_failed",
            message="组件本地状态检查失败",
            details=details,
        )

    @staticmethod
    def _capability_diagnostics(services: ApplicationServices) -> list[ErrorInfo]:
        collectors = {item.name for item in services.collectors.describe()}
        channels = {item.name for item in services.channels.describe()}
        missing: dict[tuple[str, str], list[str]] = {}
        for value in services.resources.list("sources"):
            source = SourceConfig.model_validate(value)
            if source.collector not in collectors:
                missing.setdefault(("source", source.collector), []).append(source.id)
        for value in services.resources.list("channels"):
            channel = ChannelConfig.model_validate(value)
            if channel.channel not in channels:
                missing.setdefault(("channel", channel.channel), []).append(channel.id)
        return [
            ErrorInfo(
                code="capability_missing",
                message="已保存资源引用的插件能力不可用",
                details={"kind": kind, "name": name, "resources": sorted(resources)},
            )
            for (kind, name), resources in sorted(missing.items())
        ]

    async def shutdown(self) -> None:
        self._shutdown_requested = True
        services = self._services
        if services is not None:
            # pause_admission must queue on the same lock as trigger before it
            # closes admission; setting the flag here would reject a trigger that
            # is already past its first admission check but has not submitted yet.
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
            self._shutdown = True
            self._shutdown_complete = True

    async def _cleanup_startup(self) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        await self._cleanup_owned(errors, emit_stopped=False)
        self._services = None
        self._started = False
        return errors

    async def _cleanup_owned(self, errors: list[dict[str, Any]], *, emit_stopped: bool) -> bool:
        if self._intervals is not None and self._workflow is not None:
            workflow = self._workflow

            async def pause_workflow() -> None:
                await workflow.pause_admission()

            if not await self._cleanup(
                "workflow_pause_admission",
                pause_workflow,
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
                await context.__aexit__(None, None, None)

            if not await self._cleanup(
                "checkpointer", close_checkpointer, errors, _CLEANUP_TIMEOUT
            ):
                return False
            self._checkpointer_context = None
            self._checkpointer = None

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
        sink = self._log_sink
        if sink is not None:
            sink.close()

    async def _cleanup(
        self,
        name: str,
        operation: Callable[[], Awaitable[None]],
        errors: list[dict[str, Any]],
        budget: float,
    ) -> bool:
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
        if not task.cancelled():
            task.exception()

    def _resource_view_changed(self) -> None:
        if (
            not self._shutdown_requested
            and self._resources is not None
            and self._intervals is not None
        ):
            self._intervals.update(self._resources.list("workflows"))
