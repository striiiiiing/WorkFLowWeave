"""执行本地组件探测并生成健康诊断，准入变更由生命周期协调层负责。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import Any

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import (
    ChannelConfig,
    ComponentHealth,
    DiscoveryReport,
    ErrorInfo,
    SourceConfig,
)

from .logging import JsonLogSink
from .services import ApplicationServices


def component_health(
    name: str, checked_at: datetime, error: ErrorInfo | None = None, *, required: bool = True
) -> ComponentHealth:
    """将错误映射为组件状态：必需组件不可用，可选组件降级。"""
    status = "available" if error is None else ("unavailable" if required else "degraded")
    return ComponentHealth(
        component=name, status=status, required=required, error=error, checked_at=checked_at
    )


async def health_components(
    services: ApplicationServices, sink: JsonLogSink | None, checked_at: datetime
) -> list[ComponentHealth]:
    """依次探测已装配组件，不修改运行准入或发起远程业务请求。

    配置日志文件时将日志视为必需组件，其探测会实际写入本地日志。
    """
    probes = {
        "system_config": partial(_required_paths_error, services),
        "credentials": lambda: (
            None
            if services.credentials is not None
            else ErrorInfo(code="component_unavailable", message="凭据管理组件不可用")
        ),
        "resource_store": partial(_probe_resource_store, services),
        "session_store": partial(_probe_session_store, services),
        "checkpointer": partial(_probe_checkpointer, services),
        "workflow": partial(_probe_workflow, services),
        "intervals": partial(_probe_intervals, services),
        "ai": partial(_probe_ai, services),
        "channels": partial(_probe_channels, services),
        "logging": partial(_probe_log_sink, services, sink),
    }
    return [
        await _health_component(
            name, checked_at, check, required=name != "logging" or services.log_path is not None
        )
        for name, check in probes.items()
    ]


async def _health_component(
    name: str, checked_at: datetime, check: Callable[[], Any], *, required: bool
) -> ComponentHealth:
    """统一执行同步或异步探测，将普通异常转为脱敏诊断，取消继续向上传播。"""
    try:
        error = check()
        if inspect.isawaitable(error):
            error = await error
    except Exception as exc:
        error = _component_error(name, exc)
    return component_health(name, checked_at, error, required=required)


def _required_paths_error(services: ApplicationServices) -> ErrorInfo | None:
    """检查必要路径配置是否非空，不验证文件存在性或访问权限。"""
    if not services.system_config.data_dir or not services.system_config.plugin_dir:
        return ErrorInfo(
            code="component_unavailable",
            message="系统配置缺少必要路径",
        )
    return None


def _probe_resource_store(services: ApplicationServices) -> ErrorInfo | None:
    """通过读取 Workflow 列表检查资源视图是否可用。"""
    services.resources.list("workflows")
    return None


async def _probe_session_store(services: ApplicationServices) -> ErrorInfo | None:
    """在线程中读取会话标识，检查存储访问并避免阻塞事件循环。"""
    await asyncio.to_thread(services.session_store.session_ids)
    return None


async def _probe_checkpointer(services: ApplicationServices) -> ErrorInfo | None:
    """检查初始化标记，并按注入对象支持的接口执行自检和检查点读取。

    is_setup、check 和 aget_tuple 均按能力探测，不要求所有实现提供相同自检接口。
    """
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


def _probe_workflow(services: ApplicationServices) -> ErrorInfo | None:
    """检查 Workflow 是否已关闭，不以准入暂停判定组件故障。"""
    if getattr(services.workflow, "_shutdown", False):
        return ErrorInfo(
            code="component_unavailable",
            message="Workflow 已关闭",
        )
    return None


def _probe_intervals(services: ApplicationServices) -> ErrorInfo | None:
    """检查定时触发后台任务是否存活，调度暂停本身不代表故障。"""
    if not services.intervals.scheduler.running:
        return ErrorInfo(
            code="component_unavailable",
            message="定时触发任务未运行",
        )
    return None


def _probe_ai(services: ApplicationServices) -> ErrorInfo | None:
    """检查 AI 通道管理器是否已开始关闭，不请求模型服务。"""
    if services.ai.channels._close_task is not None:
        return ErrorInfo(
            code="component_unavailable",
            message="AI 服务已关闭",
        )
    return None


def _probe_channels(services: ApplicationServices) -> ErrorInfo | None:
    """检查消息通道管理器是否正在停止，不发送探测消息。"""
    if getattr(services.channels, "_stopping", False):
        return ErrorInfo(
            code="component_unavailable",
            message="ChannelManager 正在关闭",
        )
    return None


def _probe_log_sink(services: ApplicationServices, sink: JsonLogSink | None) -> ErrorInfo | None:
    """启用日志时执行 sink 的本地写入探测，禁用日志时视为可用。"""
    if services.log_path is None:
        return None
    if sink is None:
        return ErrorInfo(code="component_unavailable", message="日志 sink 未初始化")
    return sink.check()


def _component_error(component: str, exc: Exception) -> ErrorInfo:
    """只暴露组件、异常类型和领域错误码，避免原始异常文本泄露敏感信息。"""
    details: dict[str, Any] = {
        "component": component,
        "exception_type": type(exc).__name__,
    }
    if isinstance(exc, WorkFLowWeaveError):
        details["reason"] = exc.code
    return ErrorInfo(
        code="component_check_failed",
        message="组件本地状态检查失败",
        details=details,
    )


def capability_diagnostics(services: ApplicationServices) -> list[ErrorInfo]:
    """报告缺失能力与独立接收故障，不把可选插件故障升级为核心不可用。"""
    servers = {item.id for item in services.resources.list("mcp_servers") if item.enabled}
    channels = {item.name for item in services.channels.describe()}
    missing: dict[tuple[str, str], list[str]] = {}
    for value in services.resources.list("sources"):
        source = SourceConfig.model_validate(value)
        if source.call.kind == "mcp" and source.call.server not in servers:
            missing.setdefault(("mcp_server", source.call.server), []).append(source.id)
    for value in services.resources.list("channels"):
        channel = ChannelConfig.model_validate(value)
        if channel.channel not in channels:
            missing.setdefault(("channel", channel.channel), []).append(channel.id)
    missing_errors = [
        ErrorInfo(
            code="capability_missing",
            message="已保存资源引用的插件能力不可用",
            details={"kind": kind, "name": name, "resources": sorted(resources)},
        )
        for (kind, name), resources in sorted(missing.items())
    ]
    return missing_errors + [
        error.model_copy(deep=True)
        for _, error in sorted(services.channels.receiver_errors.items())
    ]


def plugin_health(
    report: DiscoveryReport,
    diagnostics: list[ErrorInfo],
    reload_error: ErrorInfo | None,
    checked_at: datetime,
) -> ComponentHealth:
    """汇总发现错误、缺失能力与重载错误，生成可选插件的降级状态。"""
    error = None
    if report.errors or diagnostics or reload_error:
        error = ErrorInfo(
            code="plugin_degraded",
            message="可选插件存在诊断",
            details={
                "discovery_errors": [item.model_dump(mode="json") for item in report.errors],
                "capability_errors": [item.model_dump(mode="json") for item in diagnostics],
                "reload_error": reload_error.model_dump(mode="json") if reload_error else None,
            },
        )
    return component_health("plugins", checked_at, error, required=False)
