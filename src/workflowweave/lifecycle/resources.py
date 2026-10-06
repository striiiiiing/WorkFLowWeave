"""为应用装配接入资源语义校验、配置路径解析和定时计划刷新。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from workflowweave.ai import AIService
from workflowweave.channel import ChannelManager
from workflowweave.collection import CollectorManager
from workflowweave.config import ResourceStore
from workflowweave.errors import WorkFLowWeaveError, validation_error
from workflowweave.models import (
    AIConfig,
    AtSchedule,
    ChannelConfig,
    ResourceKind,
    SourceConfig,
    StrictModel,
    SystemConfig,
    copy_model,
)
from workflowweave.protocols import ChannelRegistryView, CollectorRegistryView


class LifecycleResourceStore(ResourceStore):
    """在资源成功保存或删除后通知生命周期刷新定时计划。"""

    def __init__(self, *args: Any, on_change: Callable[[], None], **kwargs: Any) -> None:
        """绑定当前事件循环，供工作线程发布资源后安全调度变更回调。"""
        self._on_change = on_change
        self._loop = asyncio.get_running_loop()
        super().__init__(*args, **kwargs)

    def _published(self) -> None:
        """在所属事件循环调用变更回调；跨线程调用时将回调入队。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is self._loop:
            self._on_change()
        else:
            self._loop.call_soon_threadsafe(self._on_change)

    def save(self, kind: str, resource: Any, *, mode: str = "upsert") -> StrictModel:
        """复用资源存储的校验与保存语义，成功后通知并返回保存结果。"""
        value = super().save(kind, resource, mode=mode)
        self._published()
        return value

    def consume_schedule(self, ident: str, expected: AtSchedule) -> bool:
        consumed = super().consume_schedule(ident, expected)
        if consumed:
            self._published()
        return consumed

    def save_many(
        self, resources: Mapping[ResourceKind, list[Any]], *, mode: str = "upsert"
    ) -> None:
        """Refresh schedules once after a successful nonempty batch."""
        super().save_many(resources, mode=mode)
        if any(resources.values()):
            self._published()

    def delete(self, kind: str, ident: str) -> None:
        """删除成功后通知计划刷新，删除失败则直接传播异常。"""
        super().delete(kind, ident)
        self._published()


def effective_config(config: SystemConfig) -> SystemConfig:
    """返回重新校验的配置副本，将相对路径解析到当前工作目录。

    保留 log_file=None 的禁用含义，将配置校验和路径解析失败转换为领域错误。
    """
    try:
        result = copy_model(config)
    except ValidationError as exc:
        raise validation_error(exc) from None
    base = Path.cwd()

    def resolved(value: str) -> str:
        """生成绝对路径，解析失败时暴露 invalid_config。"""
        try:
            path = Path(value)
            return str((path if path.is_absolute() else base / path).resolve())
        except (OSError, ValueError, RuntimeError):
            raise WorkFLowWeaveError("invalid_config", "系统路径无法解析") from None

    result.data_dir = resolved(result.data_dir)
    result.plugin_dir = resolved(result.plugin_dir)
    result.log_file = resolved(result.log_file) if result.log_file is not None else None
    return result


def resource_validators(
    collector_register: CollectorRegistryView,
    channel_register: ChannelRegistryView,
    collectors: CollectorManager,
    channels: ChannelManager,
    ai: AIService,
) -> dict[str, Callable[[StrictModel], None]]:
    """将当前运行组件的语义校验接入 ResourceStore。

    采集器或通道能力缺失时跳过该插件的语义校验，交由能力诊断报告缺失引用；
    插件重载后需重新构建这些闭包，使校验使用新注册表。
    """

    def source_validator(value: StrictModel) -> None:
        """在采集器已注册时校验采集源的运行参数。"""
        source = SourceConfig.model_validate(value)
        collectors.validate(source)

    def channel_validator(value: StrictModel) -> None:
        """在通道已注册时校验消息通道的运行参数。"""
        channel = ChannelConfig.model_validate(value)
        if channel_register.get(channel.channel) is not None:
            channels.validate(channel)

    def ai_validator(value: StrictModel) -> None:
        """通过 AI 服务校验模型配置的运行语义。"""
        ai.validate(AIConfig.model_validate(value))

    return {
        "sources": source_validator,
        "channels": channel_validator,
        "ai": ai_validator,
    }
