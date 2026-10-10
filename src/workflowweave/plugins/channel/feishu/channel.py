"""Feishu channel backed by Lark's official Channel SDK.

The SDK owns Feishu transport, event normalization, reconnects and outbound
message formatting. This adapter translates its public message model to the
WorkflowWeave channel protocol and keeps Agent admission under ChannelManager.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from pydantic import TypeAdapter

from workflowweave.channel.context import remaining_delivery_time
from workflowweave.channel.conversation import ChannelAddress, InboundHandler, InboundMessage
from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.models import ChannelConfig, Credential, Notification
from workflowweave.schema import (
    resource_options_schema,
    validate_instance,
    validate_workflow_options,
)

_CREDENTIAL_SCHEMA = TypeAdapter(Credential).json_schema()
_CREDENTIAL_ADAPTER = TypeAdapter(Credential)

_OPTIONS_SCHEMA = {
    "type": "object",
    "x-workflowweave-first-message": True,
    "additionalProperties": False,
    "$defs": _CREDENTIAL_SCHEMA.get("$defs", {}),
    "properties": {
        "app_id": {
            "type": "string",
            "minLength": 1,
            "pattern": r"^\S+$",
            "description": "飞书应用 App ID",
        },
        "app_secret": {
            "description": "飞书应用 App Secret 凭据引用",
            "anyOf": [_CREDENTIAL_SCHEMA, {"type": "null"}],
            "x-workflowweave-credential": True,
        },
        "target_kind": {
            "type": "string",
            "enum": ["chat_id", "open_id", "user_id", "email"],
            "description": "单向通知接收者类型",
            "x-workflowweave-workflow": True,
        },
        "target_id": {
            "type": "string",
            "minLength": 1,
            "pattern": r"^\S+$",
            "description": "单向通知接收者标识",
            "x-workflowweave-workflow": True,
        },
        "receive_events": {
            "type": "boolean",
            "description": "是否接收飞书文本消息事件",
            "default": True,
        },
    },
    "required": ["app_id", "app_secret"],
    "allOf": [
        {"if": {"required": ["target_id"]}, "then": {"required": ["target_kind"]}},
        {"if": {"required": ["target_kind"]}, "then": {"required": ["target_id"]}},
    ],
}


def _value(value: Any, *names: str, default: Any = None) -> Any:
    """Read an SDK model or mapping without importing SDK model classes."""

    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        result = getattr(value, name, None)
        if result is not None:
            return result
    return default


def _result_success(result: Any) -> bool:
    value = _value(result, "success", default=False)
    return bool(value() if callable(value) else value)


def _result_error_code(result: Any) -> str:
    error = _value(result, "error", default=None)
    return _error_code(error if error is not None else result)


def _error_code(error: Any) -> str:
    code = _value(error, "code", default="unknown")
    return str(getattr(code, "value", code))


def _is_uncertain_error(error: Any) -> bool:
    # Nonzero API responses explicitly reject a send, including UNKNOWN codes.
    if _value(error, "raw_code") not in (None, 0):
        return False
    return _error_code(error) in {
        "send_timeout", "unknown", "network_error", "not_connected"
    }


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _load_official_sdk() -> Any:
    """Import the optional official package only when a Feishu instance starts."""

    try:
        module = await asyncio.to_thread(importlib.import_module, "lark_channel")
    except ImportError as exc:
        raise ChannelDeliveryError(
            "feishu_dependency_missing",
            "飞书渠道需要安装 lark-channel-sdk",
            details={"package": "lark-channel-sdk"},
        ) from exc
    return module


class FeishuChannel:
    """WorkflowWeave adapter for the official ``lark-channel-sdk`` channel."""

    def __init__(
        self,
        config: ChannelConfig,
        credentials: Any,
        *,
        channel_factory: Callable[..., Any] | None = None,
    ) -> None:
        validate_instance(
            config.options, resource_options_schema(_OPTIONS_SCHEMA), path=["options"]
        )
        self._config = config
        self._options = dict(config.options)
        self._credentials = credentials
        self._channel_factory = channel_factory
        self._channel: Any = None
        self._handler: InboundHandler | None = None
        self._unsubscribe: Callable[[], Any] | None = None
        self._receiving = False
        self._receiver_generation = 0
        self._closed = False
        self._receiver_state = "stopped"
        self._receiver_error: str | None = None
        self._send_lock = asyncio.Lock()

    async def _resolve_secret(self) -> str:
        if self._credentials is None:
            raise ChannelDeliveryError("credential_resolver_missing", "飞书凭据解析器未配置")
        try:
            reference = _CREDENTIAL_ADAPTER.validate_python(self._options["app_secret"])
            secret = await self._credentials.resolve(reference)
        except Exception as exc:
            raise ChannelDeliveryError(
                "credential_invalid",
                "飞书 App Secret 凭据不可用",
                details={"exception_type": type(exc).__name__},
            ) from exc
        if not isinstance(secret, str) or not secret:
            raise ChannelDeliveryError("credential_invalid", "飞书 App Secret 凭据不可用")
        return secret

    async def start(self) -> None:
        if self._closed:
            raise ChannelDeliveryError("feishu_closed", "飞书渠道已关闭")
        if self._channel is not None:
            return
        secret = await self._resolve_secret()
        try:
            if self._channel_factory is not None:
                self._channel = self._channel_factory(
                    app_id=self._options["app_id"], app_secret=secret
                )
            else:
                sdk = await _load_official_sdk()
                # Manager owns admission, message identity and delivery attempts.
                # SDK batching, retries and chunking would change those contracts.
                self._channel = sdk.FeishuChannel(
                    app_id=self._options["app_id"],
                    app_secret=secret,
                    policy=sdk.PolicyConfig(
                        require_mention=False, respond_to_mention_all=True
                    ),
                    safety=sdk.SafetyConfig(
                        chat_queue=sdk.ChatQueueConfig(enabled=False)
                    ),
                    outbound=sdk.OutboundConfig(
                        retry=sdk.RetryConfig(max_attempts=1), text_chunk_limit=0
                    ),
                )
        except ChannelDeliveryError:
            raise
        except Exception as exc:
            raise ChannelDeliveryError(
                "feishu_client_init_failed",
                "飞书官方 SDK 客户端初始化失败",
                details={"exception_type": type(exc).__name__},
            ) from exc

    async def stop(self) -> None:
        if self._closed:
            return
        await self.stop_receiving()
        self._closed = True
        self._channel = None

    async def _disconnect(self) -> None:
        if self._channel is None:
            return
        disconnect = getattr(self._channel, "disconnect", None)
        if not callable(disconnect):
            raise ChannelDeliveryError(
                "feishu_sdk_incompatible", "lark-channel-sdk 缺少 disconnect 公共接口"
            )
        await _maybe_await(disconnect())

    async def _send(self, target: str, text: str, *, options: dict[str, Any]) -> None:
        if not text:
            raise ChannelDeliveryError("feishu_message_empty", "飞书消息内容不能为空")
        if self._channel is None:
            raise ChannelDeliveryError("feishu_not_started", "飞书渠道尚未启动")
        send = getattr(self._channel, "send", None)
        if not callable(send):
            raise ChannelDeliveryError(
                "feishu_sdk_incompatible", "lark-channel-sdk 缺少 send 公共接口"
            )
        try:
            async with asyncio.timeout(remaining_delivery_time(self._config.timeout)):
                async with self._send_lock:
                    result = await _maybe_await(send(target, {"text": text}, options))
        except TimeoutError as exc:
            raise ChannelDeliveryError(
                "feishu_delivery_timeout", "飞书消息发送超时", uncertain=True
            ) from exc
        except ChannelDeliveryError:
            raise
        except Exception as exc:
            raise ChannelDeliveryError(
                "feishu_delivery_failed",
                "飞书消息发送失败",
                uncertain=_is_uncertain_error(exc),
                details={"exception_type": type(exc).__name__},
            ) from exc
        if not _result_success(result):
            raise ChannelDeliveryError(
                "feishu_delivery_rejected",
                "飞书官方 SDK 未确认消息发送成功",
                uncertain=_is_uncertain_error(_value(result, "error")),
                details={"sdk_code": _result_error_code(result)},
            )

    async def send(self, notification: Notification, *, options: dict) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        effective = {**self._options, **deepcopy(options)}
        validate_instance(effective, _OPTIONS_SCHEMA, path=["options"])
        target_kind = effective.get("target_kind")
        target_id = effective.get("target_id")
        if not target_kind or not target_id:
            raise ChannelDeliveryError(
                "feishu_target_missing", "飞书普通发送需要设置 target_kind 和 target_id"
            )
        await self._send(
            str(target_id),
            notification.text,
            options={"receive_id_type": target_kind},
        )

    async def reply(
        self,
        notification: Notification,
        *,
        address: ChannelAddress,
        options: dict,
    ) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        if address.kind != "chat_id":
            raise ChannelDeliveryError("feishu_address_invalid", "飞书回复地址类型不受支持")
        await self._send(
            address.target,
            notification.text,
            options={
                "receive_id_type": "chat_id",
                "reply_to": address.message_id,
                "reply_target_gone": "fail",
            },
        )

    async def start_receiving(
        self, handler: InboundHandler, *, temporary: bool = False
    ) -> None:
        if self._closed:
            raise ChannelDeliveryError("feishu_closed", "飞书渠道已关闭")
        if self._channel is None:
            raise ChannelDeliveryError("feishu_not_started", "飞书渠道尚未启动")
        if self._receiving:
            raise ChannelDeliveryError("feishu_already_receiving", "飞书渠道已在接收消息")
        if not temporary and not self._options.get("receive_events", True):
            self._receiver_state = "stopped"
            return
        on = getattr(self._channel, "on", None)
        connect = getattr(self._channel, "connect_until_ready", None)
        if not callable(on) or not callable(connect):
            raise ChannelDeliveryError(
                "feishu_sdk_incompatible",
                "lark-channel-sdk 缺少 on/connect_until_ready 公共接口",
            )
        loop = asyncio.get_running_loop()
        self._receiver_generation += 1
        generation = self._receiver_generation

        async def on_message(message: Any) -> None:
            await self._on_message(message, loop=loop, generation=generation)

        self._receiver_state = "connecting"
        self._receiver_error = None
        try:
            self._handler = handler
            self._unsubscribe = on("message", on_message)
            self._receiving = True
            await _maybe_await(
                connect(timeout=remaining_delivery_time(self._config.timeout))
            )
            self._receiver_state = "running"
        except BaseException as exc:
            await self.stop_receiving()
            self._receiver_state = "stopped" if isinstance(exc, asyncio.CancelledError) else "failed"
            self._receiver_error = (
                None if isinstance(exc, asyncio.CancelledError)
                else str(getattr(exc, "code", type(exc).__name__))
            )
            raise

    async def _on_message(
        self, message: Any, *, loop: asyncio.AbstractEventLoop, generation: int
    ) -> None:
        # Official SDK callbacks run on its own background loop. Manager's
        # locks, queues and database admission belong to the application loop.
        admission = self._admit_message(message, generation=generation)
        if asyncio.get_running_loop() is loop:
            await admission
            return
        try:
            future = asyncio.run_coroutine_threadsafe(admission, loop)
        except BaseException:
            admission.close()
            raise
        await asyncio.wrap_future(future)

    async def _admit_message(self, message: Any, *, generation: int) -> None:
        if (
            generation != self._receiver_generation
            or not self._receiving
            or self._handler is None
        ):
            return
        if _value(message, "raw_content_type") != "text":
            return
        if bool(_value(message, "sender_is_bot", default=False)):
            return
        sender_type = _value(message, "sender_type", default=None)
        if sender_type in {"bot", "app"}:
            return
        conversation = _value(message, "conversation", default=None)
        chat_id = _value(message, "chat_id", default=None) or _value(
            conversation, "chat_id", default=None
        )
        sender_id = _value(message, "sender_id", default=None)
        message_id = _value(message, "message_id", "id", default=None)
        text = _value(message, "body_text", "content_text", default=None)
        chat_type = _value(message, "chat_type", default=None) or _value(
            conversation, "chat_type", default=None
        )
        if not all(isinstance(value, str) and value for value in (chat_id, sender_id, message_id)):
            return
        if not isinstance(text, str) or not text.strip():
            return
        inbound = InboundMessage(
            request_id=str(message_id),
            text=text.strip(),
            address=ChannelAddress(
                kind="chat_id",
                target=str(chat_id),
                sender=str(sender_id),
                message_id=str(message_id),
                conversation_type=(
                    "private" if chat_type == "p2p"
                    else "group" if chat_type in {"group", "topic"}
                    else None
                ),
            ),
        )
        await self._handler(inbound)

    async def stop_receiving(self) -> None:
        self._handler = None
        self._receiving = False
        self._receiver_generation += 1
        try:
            try:
                if self._unsubscribe is not None:
                    await _maybe_await(self._unsubscribe())
                    self._unsubscribe = None
            finally:
                await self._disconnect()
        except BaseException as exc:
            self._receiver_state = "failed"
            self._receiver_error = getattr(exc, "code", type(exc).__name__)
            raise
        self._receiver_state = "stopped"
        self._receiver_error = None

    def receiver_status(self) -> dict[str, Any]:
        return {"state": self._receiver_state, "error": self._receiver_error}


class FeishuChannelType:
    name = "feishu"
    id_prefix = "feishu"
    description = "飞书官方 Bot 双向消息与通知渠道"
    capabilities = ["notification", "conversation"]
    options_schema = _OPTIONS_SCHEMA

    def connection_options(self, address: ChannelAddress) -> dict[str, str] | None:
        if (
            address.kind != "chat_id"
            or address.conversation_type != "private"
            or not address.target
        ):
            return None
        return {"target_kind": "chat_id", "target_id": address.target}

    async def create(self, config: ChannelConfig, credentials: Any) -> FeishuChannel:
        return FeishuChannel(config, credentials)
