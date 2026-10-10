"""First-message connection state over the manager's existing receiver lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import ValidationError

from workflowweave.channel.conversation import InboundMessage
from workflowweave.errors import WorkFLowWeaveError, exception_error, validation_error
from workflowweave.models import ChannelConfig, ErrorInfo, JSONObject, Notification

if TYPE_CHECKING:
    from workflowweave.channel.manager import ChannelManager

FIRST_MESSAGE_TIMEOUT = 300.0
STATUS_INTERVAL = 1.0
CONNECTION_REPLY = "成功连接"
_ACTIVE = {"connecting", "waiting_message"}
PersistTarget = Callable[[ChannelConfig, JSONObject], Awaitable[ChannelConfig]]
_LOGGER = logging.getLogger(__name__)


def _confirmation_output_id(config: ChannelConfig, message: InboundMessage) -> str:
    """Build an internal delivery ID without imposing the platform ID format."""
    identity = "\x1f".join((
        config.id,
        message.request_id,
        message.address.kind,
        message.address.target,
        message.address.sender,
        message.address.message_id,
    ))
    return f"connection-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


@dataclass
class _Connection:
    config: ChannelConfig
    persist: PersistTarget
    inbound: asyncio.Future[InboundMessage]
    state: str = "connecting"
    message: str = "正在启动接收，请在开启期间给机器人发送第一条私聊消息"
    error: ErrorInfo | None = None
    target_options: JSONObject = field(default_factory=dict)
    task: asyncio.Task | None = None
    temporary_receiver: bool = False
    claimed: InboundMessage | None = None
    saving_config: ChannelConfig | None = None

    def snapshot(self) -> dict:
        return {
            "channel_id": self.config.id, "state": self.state, "message": self.message,
            "error": self.error.model_dump(mode="json") if self.error else None,
            "target_options": dict(self.target_options) if self.state == "connected" else {},
        }


class ChannelConnections:
    def __init__(self, manager: ChannelManager, *, timeout: float = FIRST_MESSAGE_TIMEOUT):
        self._manager = manager
        self._timeout = timeout
        self._sessions: dict[str, _Connection] = {}
        self._lock = asyncio.Lock()

    def snapshot(self, channel_id: str) -> dict:
        session = self._sessions.get(channel_id)
        if session is None:
            return {"channel_id": channel_id, "state": "idle", "message": "尚未开始连接",
                    "error": None, "target_options": {}}
        return session.snapshot()

    async def start(self, config: ChannelConfig, persist: PersistTarget) -> dict:
        self._manager.validate(config)
        channel = self._manager._register.get(config.channel)
        if not config.enabled:
            raise WorkFLowWeaveError("channel_disabled", "请先启用渠道")
        if getattr(channel, "connection_options", None) is None:
            raise WorkFLowWeaveError("channel_connection_unsupported", "此渠道不支持首条消息连接")
        async with self._lock:
            previous = self._sessions.get(config.id)
            if previous is not None and previous.state in _ACTIVE:
                if previous.config != config:
                    raise WorkFLowWeaveError("session_busy", "旧配置仍在连接，请先取消")
                return previous.snapshot()
            if previous is not None and previous.task is not None:
                await asyncio.gather(previous.task, return_exceptions=True)
            session = _Connection(config.model_copy(deep=True), persist,
                                  asyncio.get_running_loop().create_future())
            self._sessions[config.id] = session
            session.task = asyncio.create_task(self._run(session), name=f"channel:connect:{config.id}")
            return session.snapshot()

    def admit(self, config: ChannelConfig, message: InboundMessage) -> dict | None:
        session = self._sessions.get(config.id)
        if session is None or self._manager._key(session.config) != self._manager._key(config):
            return None
        if session.claimed is not None and message.request_id == session.claimed.request_id:
            if message != session.claimed:
                raise WorkFLowWeaveError("request_conflict", "连接消息 ID 对应了不同内容")
            return {"status": "duplicate"}
        if session.state not in _ACTIVE:
            return None
        if session.claimed is not None:
            return {"status": "connecting"}
        channel = self._manager._register.get(config.channel)
        target = channel.connection_options(message.address)
        if target is None:
            return {"status": "ignored", "reason": "private_message_required"}
        if not isinstance(target, dict) or not target:
            raise WorkFLowWeaveError("invalid_declaration", "插件未返回有效的连接目标")
        self._manager.validate(config.model_copy(update={"options": {**config.options, **target}}))
        session.target_options = dict(target)
        session.claimed = message.model_copy(deep=True)
        session.message = "已收到首条私聊消息，正在回复并保存连接"
        session.inbound.set_result(session.claimed)
        return {"status": "accepted"}

    async def _wait_message(self, session: _Connection) -> InboundMessage:
        while not session.inbound.done():
            await asyncio.wait({session.inbound}, timeout=STATUS_INTERVAL)
            receiver = self._manager.receiver(session.config)
            status = getattr(receiver, "receiver_status", None)
            if status is None:
                continue
            value = status()
            if value.get("state") in {"failed", "stopped"}:
                raise WorkFLowWeaveError(
                    "channel_receiver_failed", "消息接收已停止，请检查渠道配置后重试",
                    {"receiver_error": value.get("error")},
                )
        return session.inbound.result()

    @staticmethod
    def _fail(session: _Connection, error: ErrorInfo) -> None:
        session.state, session.message, session.error = "failed", error.message, error

    @staticmethod
    def _log(session: _Connection, event: str, **fields: object) -> None:
        """Record connection phases without platform addresses or message bodies."""
        extra = {
            "event": event,
            "channel_id": session.config.id,
            **{key: value for key, value in fields.items() if key in {
                "status", "error_code", "delivery_status", "delivery_uncertain",
            }},
        }
        _LOGGER.info(event, extra=extra)

    async def _run(self, session: _Connection) -> None:
        connected = False
        try:
            async with asyncio.timeout(self._timeout):
                await self._manager._start_connection_receiver(session)
                self._log(session, "channel_connection_receiver_started")
                session.state = "waiting_message"
                session.message = "请在开启期间给机器人发送第一条私聊消息；连接后将收到“成功连接”"
                message = await self._wait_message(session)
                self._log(session, "channel_connection_message_received")
                reply_config = session.config.model_copy(update={
                    "options": {**session.config.options, **session.target_options},
                }, deep=True)
                self._log(session, "channel_connection_confirmation_started")
                receipt = await self._manager.send(reply_config, Notification(
                    session_id="channel_connection",
                    output_id=_confirmation_output_id(session.config, message),
                    text=CONNECTION_REPLY,
                ), reply_to=message.address)
                self._log(
                    session,
                    "channel_connection_confirmation_result",
                    status=receipt.status,
                    delivery_status=receipt.status,
                    error_code=receipt.error.code if receipt.error else None,
                    delivery_uncertain=(
                        receipt.error.details.get("delivery_uncertain") if receipt.error else False
                    ),
                )
                if receipt.status != "success":
                    self._fail(session, receipt.error or ErrorInfo(
                        code="channel_connection_reply_failed", message="连接确认消息未发送成功",
                    ))
                    return
                session.saving_config = session.config.model_copy(update={
                    "options": {**session.config.options, **session.target_options},
                }, deep=True)
                session.config = await session.persist(session.config, session.target_options)
                self._log(session, "channel_connection_target_saved", status="success")
                connected = True
        except asyncio.CancelledError:
            session.state, session.message = "cancelled", "连接已取消"
            raise
        except TimeoutError:
            self._fail(session, ErrorInfo(
                code="channel_connection_timeout", message="等待首条私聊消息超时，请重新开启连接",
            ))
        except WorkFLowWeaveError as exc:
            self._fail(session, exc.info)
        except ValidationError as exc:
            self._fail(session, validation_error(exc, code="channel_connection_invalid").info)
        except Exception as exc:
            self._fail(session, exception_error(
                exc, code="channel_connection_failed", message="渠道连接失败",
            ))
        finally:
            if not session.inbound.done():
                session.inbound.cancel()
            try:
                await self._manager._stop_connection_receiver(session)
            except Exception as exc:
                connected = False
                cleanup_error = exception_error(
                    exc, code="channel_connection_cleanup_failed", message="临时消息接收清理失败",
                    details={"previous_error": session.error.model_dump() if session.error else None},
                )
                if session.error is None:
                    self._fail(session, cleanup_error)
                else:
                    session.error = session.error.model_copy(update={
                        "details": {**session.error.details, "cleanup_error": cleanup_error.model_dump()},
                    })
                self._log(session, "channel_connection_cleanup_result", status="failed",
                          error_code=cleanup_error.code)
            else:
                self._log(session, "channel_connection_cleanup_result", status="success")
            if connected:
                session.state, session.message = "connected", CONNECTION_REPLY
                self._log(session, "channel_connection_result", status="connected")
            elif session.state == "failed":
                self._log(session, "channel_connection_result", status="failed",
                          error_code=session.error.code if session.error else None)

    async def cancel(self, channel_id: str) -> dict:
        async with self._lock:
            session = self._sessions.get(channel_id)
            if session is not None and session.task is not None and not session.task.done():
                session.state, session.message = "cancelled", "连接已取消"
                session.task.cancel()
                await asyncio.gather(session.task, return_exceptions=True)
            return self.snapshot(channel_id)

    async def reconcile(self, configs: list[ChannelConfig]) -> None:
        current = {config.id: config for config in configs}
        for ident, session in list(self._sessions.items()):
            config = current.get(ident)
            if config == session.config or (
                session.saving_config is not None and config == session.saving_config
            ):
                continue
            await self.cancel(ident)
            self._sessions.pop(ident, None)

    async def close(self) -> None:
        for ident in list(self._sessions):
            await self.cancel(ident)
