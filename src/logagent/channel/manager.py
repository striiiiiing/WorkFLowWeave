from __future__ import annotations

import asyncio
import json
import logging
import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from logagent.channel.context import delivery_deadline
from logagent.channel.errors import ChannelDeliveryError
from logagent.errors import LogAgentError, exception_error
from logagent.models import (
    CapabilityDescription,
    ChannelConfig,
    DeliveryResult,
    ErrorInfo,
    Notification,
)
from logagent.schema import split_options, validate_instance

_LOGGER = logging.getLogger(__name__)
_STOP_TIMEOUT = 5.0


class _BudgetExhausted(Exception):
    """A blocking plugin call overran the send budget before the loop could time out."""


@dataclass(eq=False)
class _Entry:
    """One resident instance keyed by the effective snapshot configuration."""

    key: tuple[str, str]
    channel: str
    owner: str
    instance: Any
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stop_task: asyncio.Task[None] | None = None
    stopped: bool = False


@dataclass
class _ActiveSend:
    key: tuple[str, str]
    channel: str
    owner: str
    finished: asyncio.Event = field(default_factory=asyncio.Event)


class ChannelManager:
    def __init__(
        self,
        channel_register: Any,
        *,
        credentials: Any = None,
        stop_timeout: float = _STOP_TIMEOUT,
    ):
        if not math.isfinite(stop_timeout) or stop_timeout <= 0:
            raise ValueError("stop_timeout must be positive and finite")
        self._register = channel_register
        self._credentials = credentials
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._retired: set[_Entry] = set()
        self._init_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._release_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._reload_lock = asyncio.Lock()
        self._stopping = False
        self._blocked_types: set[str] = set()
        self._unloaded_owners: set[str] = set()
        self._active_sends: dict[asyncio.Task[Any], _ActiveSend] = {}
        self._stop_task: asyncio.Task[None] | None = None
        self._stop_timeout = stop_timeout

    def describe(self) -> list[CapabilityDescription]:
        return [x.model_copy(deep=True) for x in self._register.describe()]

    def validate(self, config: ChannelConfig) -> None:
        channel = self._register.get(config.channel)
        if channel is None:
            raise ValueError("channel_missing")
        if "notification" not in channel.capabilities:
            raise ValueError("channel_not_notification")
        validate_instance(config.options, channel.options_schema, path=["options"])

    def _instance_config(self, config: ChannelConfig) -> ChannelConfig:
        channel = self._register.get(config.channel)
        if channel is None:
            raise LogAgentError("channel_missing", "通知渠道未注册")
        instance_options, _ = split_options(config.options, channel.options_schema)
        return config.model_copy(update={"options": instance_options}, deep=True)

    def _key(self, config: ChannelConfig) -> tuple[str, str]:
        # Invocation-only fields do not change the resident target. In particular,
        # different send budgets must still join the same one-time initialization.
        effective = self._instance_config(config).model_dump(mode="json", exclude={"enabled", "timeout"})
        return (
            config.id,
            json.dumps(effective, sort_keys=True, separators=(",", ":")),
        )

    @staticmethod
    def _receipt(
        config: ChannelConfig,
        notification: Notification,
        *,
        status: str,
        attempts: int,
        error: ErrorInfo | None = None,
    ) -> DeliveryResult:
        if error is not None:
            _LOGGER.warning(
                "notification_failed",
                extra={
                    "event": "notification_failed", "session_id": notification.session_id,
                    "channel_id": config.id, "output_id": notification.output_id,
                    "error_code": error.code, "delivery_status": status,
                    "delivery_uncertain": bool(error.details.get("delivery_uncertain")),
                },
            )
        return DeliveryResult(
            channel_id=config.id,
            output_id=notification.output_id,
            status=status,
            attempts=attempts,
            error=error,
        )

    def _admit(self) -> None:
        if self._stopping:
            raise LogAgentError("channel_manager_stopping", "渠道网关正在关闭")

    def _channel_owner(self, channel: str) -> str:
        for description in self._register.describe():
            if description.name == channel:
                return description.plugin
        return ""

    async def _entry(
        self,
        key: tuple[str, str],
        channel: Any,
        config: ChannelConfig,
        *,
        deadline: float,
    ) -> _Entry:
        """Return the resident instance, starting it once for concurrent first use."""
        async with self._lock:
            init_lock = self._init_locks.setdefault(key, asyncio.Lock())
        async with init_lock:
            async with self._lock:
                self._admit()
                entry = self._entries.get(key)
                if entry is not None:
                    if entry.stop_task is not None:
                        raise LogAgentError("channel_unavailable", "渠道尚未完成关闭")
                    return entry
            instance = None
            try:
                instance = await channel.create(self._instance_config(config), self._credentials)
                if asyncio.get_running_loop().time() >= deadline:
                    raise _BudgetExhausted
                await instance.start()
                if asyncio.get_running_loop().time() >= deadline:
                    raise _BudgetExhausted
                async with self._lock:
                    self._admit()
                    entry = _Entry(key, config.channel, self._channel_owner(config.channel), instance)
                    self._entries[key] = entry
                    return entry
            except BaseException as initialization_error:
                try:
                    await self._cleanup_initialization(instance, config, key)
                except asyncio.CancelledError:
                    raise
                except BaseException as cleanup_error:
                    raise self._initialization_cleanup_error(
                        initialization_error, cleanup_error
                    ) from initialization_error
                raise

    async def _cleanup_initialization(self, instance, config, key) -> None:
        if instance is None:
            return
        entry = _Entry(key, config.channel, self._channel_owner(config.channel), instance)
        self._retired.add(entry)
        await self._stop_entry(entry)

    @staticmethod
    def _exception_summary(exc: BaseException) -> dict[str, Any]:
        return {
            "code": "channel_cleanup_failed",
            "message": "渠道清理发生异常",
            "details": {"exception_type": type(exc).__name__},
        }

    @classmethod
    def _initialization_cleanup_error(
        cls, initialization_error: BaseException, cleanup_error: BaseException
    ) -> LogAgentError:
        return LogAgentError(
            "channel_initialization_cleanup_failed",
            "通知渠道初始化失败且清理失败",
            {
                "initialization_error": cls._exception_summary(initialization_error),
                "cleanup_error": cls._exception_summary(cleanup_error),
            },
        )

    async def _begin_send(self, config: ChannelConfig) -> tuple[str, str]:
        while True:
            async with self._lock:
                self._admit()
                owner = self._channel_owner(config.channel)
                if (
                    config.channel in self._blocked_types
                    or owner in self._unloaded_owners
                ):
                    raise LogAgentError("channel_unavailable", "渠道正在卸载或替换")
                key = self._key(config)
                release_task = self._release_tasks.get(key)
                if release_task is None:
                    task = asyncio.current_task()
                    if task is None:
                        raise RuntimeError("ChannelManager.send requires an asyncio task")
                    self._active_sends[task] = _ActiveSend(key, config.channel, owner)
                    return key
            await asyncio.wait([release_task])

    def _end_send(self) -> None:
        active = self._active_sends.pop(asyncio.current_task())
        active.finished.set()

    async def send(self, config: ChannelConfig, notification: Notification) -> DeliveryResult:
        config, notification = deepcopy(config), deepcopy(notification)
        if not config.enabled:
            return self._receipt(config, notification, status="skipped", attempts=0)
        channel = self._register.get(config.channel)
        if channel is None:
            return self._receipt(
                config,
                notification,
                status="failed",
                attempts=0,
                error=ErrorInfo(code="channel_missing", message="通知渠道未注册"),
            )
        # One budget covers lock waits, instance creation, start and the single send.
        entered = False
        preparing = True
        key: tuple[str, str] | None = None
        deadline = asyncio.get_running_loop().time() + config.timeout
        timeout = asyncio.timeout(config.timeout)
        try:
            async with timeout:
                key = await self._begin_send(config)
                self.validate(config)
                channel = self._register.get(config.channel)
                entry = await self._entry(key, channel, config, deadline=deadline)
                preparing = False
                async with entry.send_lock:
                    send = entry.instance.send
                    if asyncio.get_running_loop().time() >= deadline:
                        raise _BudgetExhausted
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
                    _, options = split_options(config.options, channel.options_schema)
                    entered = True
                    budget_token = delivery_deadline.set(deadline)
                    try:
                        await send(notification, options=options)
                    finally:
                        delivery_deadline.reset(budget_token)
                    if asyncio.current_task().cancelling():
                        raise asyncio.CancelledError
            return self._receipt(config, notification, status="success", attempts=1)
        except Exception as exc:
            status = "failed"
            if isinstance(exc, _BudgetExhausted) or (
                isinstance(exc, TimeoutError) and timeout.expired()
            ):
                status = "timeout"
                error = ErrorInfo(
                    code="delivery_timeout",
                    message="通知发送超出总时限",
                    details={"delivery_uncertain": entered},
                )
            elif isinstance(exc, ChannelDeliveryError):
                error = ErrorInfo(
                    code=exc.code,
                    message=exc.info.message,
                    details={**exc.details, "delivery_uncertain": entered and exc.uncertain},
                )
            else:
                details = {"delivery_uncertain": entered}
                if isinstance(exc, LogAgentError):
                    details.update(exc.info.details)
                error = exception_error(
                    exc,
                    code="channel_prepare_failed" if preparing else "delivery_failed",
                    message="通知渠道准备失败" if preparing else "通知发送失败",
                    details=details,
                )
            return self._receipt(
                config, notification, status=status, attempts=int(entered), error=error,
            )
        finally:
            if key is not None:
                self._end_send()

    async def _stop_entry(self, entry: _Entry) -> None:
        if entry.stopped:
            return
        if entry.stop_task is None:
            entry.stop_task = asyncio.create_task(entry.instance.stop())
        try:
            await asyncio.wait_for(asyncio.shield(entry.stop_task), self._stop_timeout)
        except TimeoutError as exc:
            raise LogAgentError("channel_stop_timeout", "渠道关闭尚未完成") from exc
        entry.stopped = True
        async with self._lock:
            self._retired.discard(entry)
            if self._entries.get(entry.key) is entry:
                self._entries.pop(entry.key)
                self._init_locks.pop(entry.key, None)

    async def _wait_for_sends(self, key: tuple[str, str] | None = None) -> None:
        async with self._lock:
            pending = [active.finished.wait() for active in self._active_sends.values()
                       if key is None or active.key == key]
        await asyncio.wait_for(asyncio.gather(*pending), self._stop_timeout)

    async def _drain_and_stop(self, keys: set[tuple[str, str]]) -> None:
        for key in keys:
            try:
                await self._wait_for_sends(key)
            except TimeoutError as exc:
                raise LogAgentError(
                    "channel_release_timeout",
                    "渠道发送未在清理预算内结束",
                    {"channel_id": key[0], "timeout": self._stop_timeout},
                ) from exc

        async with self._lock:
            entries = [self._entries[key] for key in keys if key in self._entries]
        errors: list[BaseException] = []
        for entry in entries:
            try:
                await self._stop_entry(entry)
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise LogAgentError(
                "channel_release_failed",
                "通知渠道实例释放失败",
                {"errors": [self._exception_summary(exc) for exc in errors]},
            )

    async def release(self, config: ChannelConfig) -> None:
        """Release one snapshot instance after its current sends finish."""
        key = self._key(config)
        async with self._lock:
            self._admit()
            task = self._release_tasks.get(key)
            if task is None:
                task = asyncio.create_task(self._release_once(key))
                self._release_tasks[key] = task
        await asyncio.shield(task)

    async def _release_once(self, key: tuple[str, str]) -> None:
        try:
            await self._wait_for_sends(key)
            async with self._lock:
                entry = self._entries.get(key)
            if entry is not None:
                await self._stop_entry(entry)
        finally:
            async with self._lock:
                self._release_tasks.pop(key, None)

    async def unload_owner(self, owner: str) -> None:
        """Close admission for the owner before draining its resident instances."""
        async with self._reload_lock:
            async with self._lock:
                self._admit()
                self._unloaded_owners.add(owner)
                keys = {
                    entry.key for entry in self._entries.values() if entry.owner == owner
                } | {
                    active.key for active in self._active_sends.values() if active.owner == owner
                }
            await self._drain_and_stop(keys)

    async def replace_register(self, channel_register: Any) -> None:
        """Replace changed implementations, including registrations with the same name."""
        async with self._reload_lock:
            async with self._lock:
                self._admit()
                old_names = {item.name for item in self._register.describe()} | {
                    entry.channel for entry in self._entries.values()
                }
                new_owners = {item.name: item.plugin for item in channel_register.describe()}
                changed = set()
                for name in old_names:
                    old, new = self._register.get(name), channel_register.get(name)
                    if (
                        old is None or new is None or old.create != new.create
                        or old.options_schema != new.options_schema
                        or old.capabilities != new.capabilities
                        or self._channel_owner(name) != new_owners.get(name)
                        or self._channel_owner(name) in self._unloaded_owners
                    ):
                        changed.add(name)
                self._blocked_types.update(changed)
                keys = {
                    entry.key for entry in self._entries.values() if entry.channel in changed
                } | {
                    active.key for active in self._active_sends.values() if active.channel in changed
                }
            # On failure retain old registrations and blocked admission; callers
            # can retry cleanup without losing ownership of unfinished instances.
            await self._drain_and_stop(keys)
            async with self._lock:
                self._register = channel_register
                self._blocked_types.difference_update(changed)
                self._unloaded_owners.difference_update(
                    item.plugin for item in channel_register.describe()
                )

    async def reload_register(self, channel_register: Any) -> None:
        """Lifecycle-facing alias for replacing the readonly registry view."""
        await self.replace_register(channel_register)

    async def stop(self) -> None:
        async with self._lock:
            if self._stop_task is None or (
                self._stop_task.done() and (self._entries or self._retired or self._active_sends)
            ):
                self._stopping = True
                self._stop_task = asyncio.create_task(self._stop_entries())
            stop_task = self._stop_task
        await asyncio.shield(stop_task)

    async def _stop_entries(self) -> None:
        try:
            await self._wait_for_sends()
        except TimeoutError:
            # Drain first; after the budget expires cancellation prevents new
            # external operations and lets send finally blocks release ownership.
            for task in tuple(self._active_sends):
                task.cancel()
            try:
                await self._wait_for_sends()
            except TimeoutError as exc:
                raise LogAgentError(
                    "channel_stop_failed", "活动渠道调用未响应取消",
                    {"active_sends": len(self._active_sends)},
                ) from exc
        async with self._lock:
            entries = [*self._entries.values(), *self._retired]
            releases = list(self._release_tasks.values())
        results = await asyncio.gather(
            *(self._stop_entry(entry) for entry in entries),
            *releases, return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise LogAgentError(
                "channel_stop_failed", "通知渠道实例关闭失败",
                {"errors": [self._exception_summary(exc) for exc in errors]},
            ) from errors[0]
