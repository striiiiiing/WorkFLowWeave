"""按连接配置管理渠道复用、并发启动、活动操作和关闭过程。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from logagent.ai.channels import AIChannel, ChannelFactory
from logagent.errors import LogAgentError
from logagent.models import AIConfig, copy_model


@dataclass
class _Entry:
    """记录一个渠道的启动任务、当前使用者及唯一关闭任务。

    管理器保留已关闭条目，使后续调用必须显式请求重启，不能隐式重新连通。
    """

    channel: AIChannel
    starting: asyncio.Task | None = None
    tasks: set[asyncio.Task] = field(default_factory=set)
    closing: asyncio.Task | None = None


def _key(config: AIConfig) -> str:
    """根据 provider、base_url 和凭据引用生成连接标识。

    提示词与模型参数变更不创建新连接；地址或凭据引用变更创建独立连接，
    使既有 Workflow 快照仍能沿用原渠道。这里不解析或散列凭据明文。
    """
    connection = config.model_dump(include={"provider", "base_url", "api_key"}, mode="json")
    return hashlib.sha256(json.dumps(connection, sort_keys=True).encode()).hexdigest()


class ChannelManager:
    """以连接标识复用渠道，并协调使用者与资源清理。

    单渠道关闭后可显式重启；管理器整体关闭后不再接受新的渠道。
    """

    def __init__(self, factories: Mapping[str, ChannelFactory], close_timeout: float):
        """复制渠道工厂映射，并保存每个渠道清理操作的秒级预算。"""
        self.factories = dict(factories)
        self.close_timeout = close_timeout
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._close_task: asyncio.Task | None = None

    async def _get(self, config: AIConfig, *, restart: bool = False) -> _Entry:
        """取得已启动条目，必要时串行创建同一连接的唯一实例。

        restart 为 True 时等待旧实例关闭后重建；普通调用不能重新打开已关闭
        渠道。启动失败或等待者被取消时发起清理；全局关闭期间禁止创建新实例。
        """
        key = _key(config)
        async with self._locks.setdefault(key, asyncio.Lock()):
            if self._close_task is not None:
                raise LogAgentError("ai_closed", "AI 服务已关闭")
            entry = self._entries.get(key)
            if entry is not None and entry.closing is not None:
                if not restart:
                    raise LogAgentError("channel_closed", "AI 渠道已关闭，请显式启动")
                await asyncio.shield(entry.closing)
                if self._close_task is not None:
                    raise LogAgentError("ai_closed", "AI 服务已关闭")
                entry = None
            if entry is None:
                channel = self.factories[config.provider].create(copy_model(config))
                entry = _Entry(channel)
                self._entries[key] = entry
                entry.starting = asyncio.create_task(channel.start())
        try:
            await asyncio.shield(entry.starting)
        except BaseException:
            if entry.closing is None:
                entry.closing = asyncio.create_task(self._close_entry(entry))
            await asyncio.shield(entry.closing)
            raise
        if self._close_task is not None or entry.closing is not None:
            raise LogAgentError("channel_closed", "AI 渠道在启动期间关闭")
        return entry

    async def start(self, config: AIConfig) -> None:
        """显式启动渠道；已有可用实例直接复用，已关闭实例等待清理后重建。"""
        await self._get(config, restart=True)

    @asynccontextmanager
    async def lease(self, config: AIConfig):
        """借用已启动渠道，并在上下文内登记当前协程任务。

        Yields:
            供当前操作使用的渠道。退出时只移除使用者记录，不关闭共享连接。

        登记的任务会在渠道关闭时收到取消请求。
        """
        entry = await self._get(config)
        task = asyncio.current_task()
        entry.tasks.add(task)
        try:
            yield entry.channel
        finally:
            entry.tasks.discard(task)

    async def _close_entry(self, entry: _Entry) -> None:
        """在清理预算内取消启动与活动任务，等待退出并释放渠道资源。

        等待任务结束时保留各任务自身的结果处理，清理失败或超时向上抛出。
        """
        async with asyncio.timeout(self.close_timeout):
            tasks = list(entry.tasks)
            if entry.starting is not None:
                tasks.append(entry.starting)
            for task in tasks:
                task.cancel()
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                await entry.channel.close()

    async def stop(self, config: AIConfig) -> None:
        """关闭指定连接并保留关闭标记，阻止后续调用隐式启动。

        同一连接的并发关闭共享一个任务；调用者取消等待不会取消正在进行的清理。
        """
        key = _key(config)
        async with self._locks.setdefault(key, asyncio.Lock()):
            entry = self._entries.get(key)
            if entry is None:
                channel = self.factories[config.provider].create(copy_model(config))
                entry = _Entry(channel)
                self._entries[key] = entry
            if entry.closing is None:
                entry.closing = asyncio.create_task(self._close_entry(entry))
        await asyncio.shield(entry.closing)

    async def close(self) -> None:
        """创建或等待唯一的全局关闭任务，使重复关闭得到同一清理结果。"""
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_all())
        await asyncio.shield(self._close_task)

    async def _close_all(self) -> None:
        """尝试关闭所有已登记渠道，并以 ai_cleanup_failed 汇总清理异常类型。"""
        entries = list(self._entries.values())
        for entry in entries:
            if entry.closing is None:
                entry.closing = asyncio.create_task(self._close_entry(entry))
        results = await asyncio.gather(*(entry.closing for entry in entries), return_exceptions=True)
        failures = [type(result).__name__ for result in results if isinstance(result, BaseException)]
        if failures:
            raise LogAgentError("ai_cleanup_failed", "AI 渠道清理失败", {"failures": failures})
