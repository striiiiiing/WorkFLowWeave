"""Telegram channel backed by python-telegram-bot's async Application API."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from pydantic import TypeAdapter

from workflowweave.channel.conversation import ChannelAddress, InboundHandler, InboundMessage
from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.models import ChannelConfig, Credential, Notification
from workflowweave.schema import resource_options_schema, validate_instance, validate_workflow_options

_CREDENTIAL_SCHEMA = TypeAdapter(Credential).json_schema()
_OPTIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "$defs": _CREDENTIAL_SCHEMA.get("$defs", {}),
    "properties": {
        "token": {
            "description": "Telegram Bot API token 凭据引用",
            "anyOf": [_CREDENTIAL_SCHEMA, {"type": "null"}],
            "x-workflowweave-credential": True,
        },
        "chat_id": {
            "type": ["string", "integer"],
            "description": "单向通知的 Telegram chat ID",
            "x-workflowweave-workflow": True,
        },
    },
    "required": ["token"],
}
_CREDENTIAL_ADAPTER = TypeAdapter(Credential)


class TelegramChannel:
    def __init__(
        self,
        config: ChannelConfig,
        credentials: Any,
        *,
        application_factory: Callable[[str], Any] | None = None,
    ):
        validate_instance(config.options, resource_options_schema(_OPTIONS_SCHEMA), path=["options"])
        self._options = dict(config.options)
        self._credentials = credentials
        self._application_factory = application_factory
        self._application: Any = None
        self._token: str | None = None
        self._handler: InboundHandler | None = None
        self._polling = False
        self._handler_registered = False
        self._initialized = False
        self._started = False
        self._stopping = False

    async def start(self) -> None:
        if self._stopping:
            raise ChannelDeliveryError("telegram_closed", "Telegram 渠道已关闭")
        if self._application is not None:
            return
        self._token = await self._resolve_token()
        try:
            if self._application_factory is not None:
                self._application = self._application_factory(self._token)
            else:
                from telegram.ext import Application

                self._application = Application.builder().token(self._token).build()
        except ImportError as exc:
            raise ChannelDeliveryError(
                "telegram_sdk_missing", "Telegram 渠道需要安装 python-telegram-bot SDK",
                details={"package": "python-telegram-bot"},
            ) from exc
        except Exception as exc:
            raise ChannelDeliveryError(
                "telegram_sdk_invalid", "Telegram Application 创建失败",
                details={"exception_type": type(exc).__name__},
            ) from exc
        # Initialize the Bot once during the resident channel lifecycle so
        # one-way sends do not race Application's lazy request setup.
        await self._call("initialize")
        self._initialized = True

    async def send(self, notification: Notification, *, options: dict) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        target = {**self._options, **options}.get("chat_id")
        if target is None:
            raise ChannelDeliveryError("telegram_target_missing", "Telegram 普通发送需要配置 chat_id")
        await self._send_message(target, notification.text)

    async def reply(
        self,
        notification: Notification,
        *,
        address: ChannelAddress,
        options: dict,
    ) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        if address.kind != "telegram":
            raise ChannelDeliveryError("telegram_address_invalid", "Telegram 回复地址类型不受支持")
        try:
            reply_to = int(address.message_id)
        except ValueError as exc:
            raise ChannelDeliveryError("telegram_address_invalid", "Telegram message ID 无效") from exc
        await self._send_message(address.target, notification.text, reply_to=reply_to)

    async def start_receiving(self, handler: InboundHandler) -> None:
        if self._application is None:
            raise ChannelDeliveryError("telegram_not_started", "Telegram 渠道尚未启动")
        updater = getattr(self._application, "updater", None)
        if self._polling or bool(getattr(updater, "running", False)):
            raise ChannelDeliveryError("telegram_already_receiving", "Telegram 渠道已在接收消息")
        self._handler = handler
        try:
            from telegram.ext import MessageHandler, filters
        except ImportError as exc:
            raise ChannelDeliveryError(
                "telegram_sdk_missing", "Telegram 渠道需要安装 python-telegram-bot SDK",
                details={"package": "python-telegram-bot"},
            ) from exc
        if not self._handler_registered:
            self._application.add_handler(
                MessageHandler(filters.TEXT, self._on_update)
            )
            self._handler_registered = True
        if not self._initialized:
            await self._call("initialize")
            self._initialized = True
        if not self._started:
            await self._call("start")
            self._started = True
        start_polling = getattr(updater, "start_polling", None)
        if not callable(start_polling):
            raise ChannelDeliveryError("telegram_sdk_invalid", "Telegram Application 缺少 polling updater")
        result = start_polling()
        if inspect.isawaitable(result):
            await result
        self._polling = bool(getattr(updater, "running", True))

    async def stop_receiving(self) -> None:
        if self._application is None:
            return
        updater = getattr(self._application, "updater", None)
        stop_polling = getattr(updater, "stop", None)
        if callable(stop_polling) and bool(getattr(updater, "running", self._polling)):
            result = stop_polling()
            if inspect.isawaitable(result):
                await result
        self._polling = False
        self._handler = None

    async def stop(self) -> None:
        self._stopping = True
        await self.stop_receiving()
        if self._application is not None:
            if self._started:
                await self._call("stop")
                self._started = False
            if self._initialized:
                await self._call("shutdown")
                self._initialized = False
        self._application = None

    async def _on_update(self, update: Any, context: Any = None) -> None:
        del context
        message = getattr(update, "effective_message", None)
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        if message is None or chat is None or self._handler is None:
            return
        user_id = getattr(user, "id", None)
        allowed = self._options.get("allowed_user_ids", [])
        if allowed and user_id not in allowed and str(user_id) not in {str(item) for item in allowed}:
            return
        text = getattr(message, "text", None)
        message_id = getattr(message, "message_id", None)
        chat_id = getattr(chat, "id", None)
        if (
            not isinstance(text, str)
            or not text.strip()
            or type(message_id) is not int
            or message_id <= 0
            or type(chat_id) is not int
            or chat_id == 0
            or type(user_id) is not int
            or user_id <= 0
        ):
            return
        address = ChannelAddress(
            kind="telegram", target=str(chat_id), sender=str(user_id), message_id=str(message_id)
        )
        await self._handler(InboundMessage(
            request_id=f"{chat_id}:{message_id}",
            text=text.strip(),
            address=address,
        ))

    async def _send_message(self, chat_id: Any, text: str, *, reply_to: int | None = None) -> None:
        if self._application is None:
            raise ChannelDeliveryError("telegram_not_started", "Telegram 渠道尚未启动")
        bot = getattr(self._application, "bot", None)
        method = getattr(bot, "send_message", None)
        if not callable(method):
            raise ChannelDeliveryError("telegram_sdk_invalid", "Telegram Bot 缺少 send_message 方法")
        kwargs: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to is not None:
            kwargs["reply_to_message_id"] = reply_to
        try:
            result = method(**kwargs)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError

            details = {"exception_type": type(exc).__name__}
            if isinstance(exc, RetryAfter):
                raise ChannelDeliveryError(
                    "telegram_rate_limited", "Telegram 限流拒绝了消息",
                    details=details,
                ) from exc
            if isinstance(exc, BadRequest):
                raise ChannelDeliveryError(
                    "telegram_rejected", "Telegram API 拒绝了消息",
                    details=details,
                ) from exc
            if isinstance(exc, NetworkError):
                raise ChannelDeliveryError(
                    "telegram_send_uncertain", "Telegram 网络错误，消息是否受理不确定",
                    details=details, uncertain=True,
                ) from exc
            if isinstance(exc, TelegramError):
                raise ChannelDeliveryError(
                    "telegram_rejected", "Telegram API 拒绝了消息",
                    details=details,
                ) from exc
            raise ChannelDeliveryError(
                "telegram_send_uncertain", "Telegram 消息发送结果不确定",
                details=details, uncertain=True,
            ) from exc
        message_id = getattr(result, "message_id", None)
        if type(message_id) is not int or message_id <= 0:
            raise ChannelDeliveryError(
                "telegram_send_uncertain", "Telegram API 未返回可验证的消息 ID",
                details={"response": "message_id_missing"}, uncertain=True,
            )

    async def _call(self, name: str, *, missing_ok: bool = False) -> None:
        method = getattr(self._application, name, None)
        if not callable(method):
            if missing_ok:
                return
            raise ChannelDeliveryError("telegram_sdk_invalid", f"Telegram Application 缺少 {name} 方法")
        result = method()
        if inspect.isawaitable(result):
            await result

    async def _resolve_token(self) -> str:
        if self._credentials is None:
            raise ChannelDeliveryError("credential_resolver_missing", "Telegram 凭据解析器未配置")
        try:
            credential = _CREDENTIAL_ADAPTER.validate_python(self._options["token"])
            value = await self._credentials.resolve(credential)
        except Exception as exc:
            raise ChannelDeliveryError(
                "credential_invalid", "Telegram Bot token 凭据不可用",
                details={"exception_type": type(exc).__name__},
            ) from exc
        if not isinstance(value, str) or not value:
            raise ChannelDeliveryError("credential_invalid", "Telegram Bot token 凭据不可用")
        return value


class TelegramChannelType:
    name = "telegram"
    id_prefix = "telegram"
    description = "Telegram Bot 双向消息与通知渠道"
    capabilities = ["notification", "conversation"]
    options_schema = _OPTIONS_SCHEMA

    async def create(self, config: ChannelConfig, credentials: Any) -> TelegramChannel:
        return TelegramChannel(config, credentials)
