"""Tencent QQ Bot channel backed by the official ``qq-botpy`` SDK.

The SDK is deliberately imported only when an instance is created.  This keeps
plugin discovery useful on installations that do not install every optional
channel dependency; the registry can report the unavailable channel when it is
actually selected.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any

from pydantic import TypeAdapter

from logagent.channel.conversation import ChannelAddress, InboundHandler, InboundMessage
from logagent.channel.errors import ChannelDeliveryError
from logagent.models import ChannelConfig, Credential, Notification
from logagent.schema import resource_options_schema, validate_instance, validate_workflow_options

_LOGGER = logging.getLogger(__name__)
_CREDENTIAL_SCHEMA = TypeAdapter(Credential).json_schema()

_OPTIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "$defs": _CREDENTIAL_SCHEMA.get("$defs", {}),
    "properties": {
        "app_id": {
            "type": "string",
            "minLength": 1,
            "pattern": r"^\S+$",
            "description": "QQ 开放平台 Bot App ID",
        },
        "client_secret": {
            "description": "QQ Bot Client Secret 凭据引用",
            "anyOf": [_CREDENTIAL_SCHEMA, {"type": "null"}],
            "x-logagent-credential": True,
        },
        "target_kind": {
            "type": "string",
            "enum": ["c2c", "group", "guild", "dm"],
            "description": "单向通知目标类型",
        },
        "target_id": {
            "type": "string",
            "minLength": 1,
            "pattern": r"^\S+$",
            "description": "单向通知目标标识",
        },
    },
    "required": ["app_id", "client_secret"],
    "allOf": [
        {"if": {"required": ["target_id"]}, "then": {"required": ["target_kind"]}},
        {"if": {"required": ["target_kind"]}, "then": {"required": ["target_id"]}},
    ],
}
_CREDENTIAL_ADAPTER = TypeAdapter(Credential)


def _value(value: Any, *names: str, default: Any = None) -> Any:
    """Read an SDK model or a test double without depending on its shape."""
    for name in names:
        result = getattr(value, name, None)
        if result is not None:
            return result
        if isinstance(value, dict) and name in value:
            return value[name]
    return default


class QQChannel:
    """Resident QQ adapter using botpy's event client and API methods."""

    def __init__(
        self,
        config: ChannelConfig,
        credentials: Any,
        *,
        client_factory: Callable[..., Any] | None = None,
    ):
        validate_instance(config.options, resource_options_schema(_OPTIONS_SCHEMA), path=["options"])
        self._options = dict(config.options)
        self._credentials = credentials
        self._client_factory = client_factory
        self._timeout = config.timeout
        self._client: Any = None
        self._runner: asyncio.Task[Any] | None = None
        self._handler: InboundHandler | None = None
        self._stopping = False
        self._routes: dict[str, Any] = {}
        self._gateway_coro: Any = None

    async def start(self) -> None:
        if self._stopping:
            raise ChannelDeliveryError("qq_closed", "QQ 渠道已关闭")
        if self._client is not None:
            return
        try:
            import botpy
        except ImportError as exc:
            raise ChannelDeliveryError(
                "qq_sdk_missing", "QQ 渠道需要安装腾讯官方 qq-botpy SDK",
                details={"package": "qq-botpy"},
            ) from exc
        secret = await self._resolve_secret()
        factory = self._client_factory or self._make_client_factory(botpy)
        intents = self._intents(botpy)
        try:
            self._client = factory(intents=intents)
        except TypeError:
            self._client = factory()
        self._client._logagent_emit = self._emit_message
        self._appid = self._options["app_id"]
        self._secret = secret
        # botpy exposes an async ``Client.start`` in addition to the blocking
        # ``run`` convenience wrapper.  Asking it for ``ret_coro`` performs
        # token/login setup and leaves the gateway coroutine for the explicit
        # Agent receiver lifecycle below.  This also makes one-way sends work
        # without implicitly subscribing the channel to inbound events.
        sdk_start = getattr(self._client, "start", None)
        if callable(sdk_start) and inspect.iscoroutinefunction(sdk_start):
            try:
                self._gateway_coro = await sdk_start(
                    appid=self._appid, secret=self._secret, ret_coro=True
                )
            except Exception as exc:
                raise ChannelDeliveryError(
                    "qq_authentication_failed", "QQ Bot 登录失败",
                    details={"exception_type": type(exc).__name__},
                ) from exc

    async def send(self, notification: Notification, *, options: dict) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        kind, target = self._options.get("target_kind"), self._options.get("target_id")
        if not kind or not target:
            raise ChannelDeliveryError("qq_target_missing", "QQ 普通发送需要配置 target_kind 和 target_id")
        await self._send_via_api(notification.text, kind=kind, target=target)

    async def reply(
        self,
        notification: Notification,
        *,
        address: ChannelAddress,
        options: dict,
    ) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        if address.kind not in {"c2c", "group", "guild", "dm"}:
            raise ChannelDeliveryError("qq_address_invalid", "QQ 回复地址类型不受支持")
        original = self._routes.get(address.message_id)
        if original is not None and callable(getattr(original, "reply", None)):
            try:
                await original.reply(content=notification.text)
                return
            except Exception as exc:
                raise ChannelDeliveryError(
                    "qq_send_failed", "QQ 原路回复失败",
                    details={"exception_type": type(exc).__name__},
                ) from exc
        await self._send_via_api(
            notification.text,
            kind=address.kind,
            target=address.target,
            message_id=address.message_id,
        )

    async def start_receiving(self, handler: InboundHandler) -> None:
        if self._client is None:
            raise ChannelDeliveryError("qq_not_started", "QQ 渠道尚未启动")
        if self._runner is not None:
            raise ChannelDeliveryError("qq_already_receiving", "QQ 渠道已在接收消息")
        self._handler = handler
        run = getattr(self._client, "run", None)
        if self._gateway_coro is not None:
            gateway = self._gateway_coro
            self._gateway_coro = None
            self._runner = asyncio.create_task(gateway, name="qq-botpy")
            return
        if not callable(run):
            raise ChannelDeliveryError("qq_sdk_invalid", "qq-botpy 客户端缺少 run 方法")
        if inspect.iscoroutinefunction(run):
            self._runner = asyncio.create_task(
                run(appid=self._appid, secret=self._secret), name="qq-botpy"
            )
        else:
            # botpy currently exposes a blocking run() entrypoint. Keep it in a
            # managed task so Manager stop/reload can own its lifetime.
            self._runner = asyncio.create_task(
                asyncio.to_thread(run, appid=self._appid, secret=self._secret),
                name="qq-botpy",
            )

    async def stop_receiving(self) -> None:
        runner, self._runner = self._runner, None
        self._handler = None
        if self._client is not None:
            for name in ("close", "stop"):
                method = getattr(self._client, name, None)
                if callable(method):
                    result = method()
                    if inspect.isawaitable(result):
                        await result
                    break
        if runner is not None:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    async def stop(self) -> None:
        self._stopping = True
        await self.stop_receiving()
        self._client = None

    @staticmethod
    def _intents(botpy: Any) -> Any:
        intents_cls = getattr(botpy, "Intents", None)
        if intents_cls is None:
            return None
        try:
            return intents_cls(
                public_messages=True,
                public_guild_messages=True,
                direct_message=True,
                guild_messages=True,
            )
        except TypeError:
            return intents_cls.default()

    def _make_client_factory(self, botpy: Any) -> Callable[..., Any]:
        parent = botpy.Client
        emit = self._emit_message

        class Client(parent):
            async def on_c2c_message_create(self, message):
                await emit("c2c", message)

            async def on_group_at_message_create(self, message):
                await emit("group", message)

            async def on_at_message_create(self, message):
                await emit("guild", message)

            async def on_direct_message_create(self, message):
                await emit("dm", message)

        return Client

    async def _resolve_secret(self) -> str:
        if self._credentials is None:
            raise ChannelDeliveryError("credential_resolver_missing", "QQ 凭据解析器未配置")
        try:
            credential = _CREDENTIAL_ADAPTER.validate_python(self._options["client_secret"])
            value = await self._credentials.resolve(credential)
        except Exception as exc:
            raise ChannelDeliveryError(
                "credential_invalid", "QQ Client Secret 凭据不可用",
                details={"exception_type": type(exc).__name__},
            ) from exc
        if not isinstance(value, str) or not value:
            raise ChannelDeliveryError("credential_invalid", "QQ Client Secret 凭据不可用")
        return value

    async def _emit_message(self, kind: str, message: Any) -> None:
        message_id = _value(message, "id", "message_id")
        content = _value(message, "content", "text")
        author = _value(message, "author", "member", default=None)
        sender = _value(author, "id", "user_openid", "member_openid", default=None)
        target = {
            "c2c": sender,
            "group": _value(message, "group_openid", default=None),
            "guild": _value(message, "channel_id", default=None),
            "dm": _value(message, "guild_id", default=None),
        }.get(kind)
        if not all(isinstance(item, str) and item for item in (message_id, sender, target, content)):
            return
        if self._handler is None:
            return
        address = ChannelAddress(kind=kind, target=target, sender=sender, message_id=message_id)
        self._routes[message_id] = message
        await self._handler(InboundMessage(request_id=message_id, text=content.strip(), address=address))

    async def _send_via_api(
        self, text: str, *, kind: str, target: str, message_id: str | None = None
    ) -> None:
        if self._client is None:
            raise ChannelDeliveryError("qq_not_started", "QQ 渠道尚未启动")
        if self._gateway_coro is not None and self._runner is None:
            gateway = self._gateway_coro
            self._gateway_coro = None
            self._runner = asyncio.create_task(gateway, name="qq-botpy")
        api = getattr(self._client, "api", None)
        if api is None:
            raise ChannelDeliveryError("qq_sdk_invalid", "qq-botpy 客户端缺少 API 入口")
        method_names = {
            "c2c": ("post_c2c_message",),
            "group": ("post_group_message",),
            "guild": ("post_message",),
            "dm": ("post_dms_message", "post_dms"),
        }[kind]
        method = next((getattr(api, name, None) for name in method_names if callable(getattr(api, name, None))), None)
        if method is None:
            raise ChannelDeliveryError("qq_sdk_invalid", f"qq-botpy 不支持 {kind} 消息发送")
        kwargs = {
            "content": text,
            "openid": target if kind == "c2c" else None,
            "group_openid": target if kind == "group" else None,
            "channel_id": target if kind == "guild" else None,
            "guild_id": target if kind == "dm" else None,
        }
        if message_id:
            kwargs["msg_id"] = message_id
        kwargs = {key: value for key, value in kwargs.items() if value is not None}
        try:
            result = method(**kwargs)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            raise ChannelDeliveryError(
                "qq_send_failed", "QQ 消息发送失败",
                details={"exception_type": type(exc).__name__, "kind": kind},
                uncertain=True,
            ) from exc


class QQChannelType:
    name = "qq"
    id_prefix = "qq"
    description = "QQ 官方 Bot 双向消息与通知渠道"
    capabilities = ["notification", "conversation"]
    options_schema = _OPTIONS_SCHEMA

    async def create(self, config: ChannelConfig, credentials: Any) -> QQChannel:
        return QQChannel(config, credentials)
