"""Tencent QQ Bot channel backed by the official ``qq-botpy`` SDK.

The SDK is deliberately imported only when an instance is created.  This keeps
plugin discovery useful on installations that do not install every optional
channel dependency; the registry can report the unavailable channel when it is
actually selected.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import time
from collections.abc import Callable
from copy import deepcopy
from logging.handlers import TimedRotatingFileHandler
from types import MethodType
from typing import Any

from pydantic import TypeAdapter

from workflowweave.channel.conversation import ChannelAddress, InboundHandler, InboundMessage
from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.models import ChannelConfig, Credential, Notification
from workflowweave.schema import (
    resource_options_schema,
    validate_instance,
    validate_workflow_options,
)

_LOGGER = logging.getLogger(__name__)
_CREDENTIAL_SCHEMA = TypeAdapter(Credential).json_schema()

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
            "description": "QQ 开放平台 Bot App ID",
        },
        "client_secret": {
            "description": "QQ Bot Client Secret 凭据引用",
            "anyOf": [_CREDENTIAL_SCHEMA, {"type": "null"}],
            "x-workflowweave-credential": True,
        },
        "target_kind": {
            "type": "string",
            "enum": ["c2c", "group", "guild", "dm"],
            "description": "通知目标类型：c2c 为好友、group 为群、guild 为频道、dm 为频道私信。"
                           "好友/群消息受首次互动及平台发送权限限制，需用户先发消息建立互动；"
                           "插件无法自动代替用户完成首次互动。",
            "x-workflowweave-workflow": True,
        },
        "target_id": {
            "type": "string",
            "minLength": 1,
            "pattern": r"^\S+$",
            "description": "对应目标类型的平台 ID（不是普通 QQ 号码）；好友/群 ID 通常来自入站事件。"
                           "首次使用请先给机器人发消息，或在群里 @机器人；仅填写 ID 不会建立互动。",
            "x-workflowweave-workflow": True,
        },
    },
    "required": ["app_id", "client_secret"],
    "allOf": [
        {"if": {"required": ["target_id"]}, "then": {"required": ["target_kind"]}},
        {"if": {"required": ["target_kind"]}, "then": {"required": ["target_id"]}},
    ],
}
_CREDENTIAL_ADAPTER = TypeAdapter(Credential)


def _clear_sdk_log_handlers() -> None:
    """Remove botpy-owned file sinks without flushing them on the event loop."""
    sdk_logger = logging.getLogger("botpy")
    for handler in list(sdk_logger.handlers):
        if not isinstance(handler, TimedRotatingFileHandler):
            continue
        sdk_logger.removeHandler(handler)
        handler.close()


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
        self._gateway_coro: Any = None
        self._botpy: Any = None
        self._receiver_state = "stopped"
        self._receiver_error: str | None = None

    async def start(self) -> None:
        if self._stopping:
            raise ChannelDeliveryError("qq_closed", "QQ 渠道已关闭")
        if self._client is not None:
            return
        try:
            botpy = await asyncio.to_thread(importlib.import_module, "botpy")
        except ImportError as exc:
            raise ChannelDeliveryError(
                "qq_sdk_missing", "QQ 渠道需要安装腾讯官方 qq-botpy SDK",
                details={"package": "qq-botpy"},
            ) from exc
        self._botpy = botpy
        await self._initialize_client()

    async def _initialize_client(self) -> None:
        if self._client is not None:
            return
        botpy = self._botpy
        if botpy is None:
            raise ChannelDeliveryError("qq_not_started", "QQ 渠道尚未启动")
        secret = await self._resolve_secret()
        if getattr(getattr(botpy, "Client", None), "__module__", "").split(".", 1)[0] == "botpy":
            await asyncio.to_thread(_clear_sdk_log_handlers)
        factory = self._client_factory or self._make_client_factory(botpy)
        intents = self._intents(botpy)
        self._client = factory(intents=intents)
        self._client._workflowweave_emit = self._emit_message
        self._appid = self._options["app_id"]
        self._secret = secret
        # botpy exposes an async ``Client.start`` in addition to the blocking
        # ``run`` convenience wrapper.  Asking it for ``ret_coro`` performs
        # token/login setup and leaves the gateway coroutine for the explicit
        # Agent receiver lifecycle below.  This also makes one-way sends work
        # without implicitly subscribing the channel to inbound events.
        sdk_start = getattr(self._client, "start", None)
        if not callable(sdk_start) or not inspect.iscoroutinefunction(sdk_start):
            raise ChannelDeliveryError("qq_sdk_invalid", "qq-botpy Client 缺少异步 start API")
        try:
            self._gateway_coro = await sdk_start(
                appid=self._appid, secret=self._secret, ret_coro=True
            )
        except ChannelDeliveryError:
            raise
        except Exception as exc:
            raise ChannelDeliveryError(
                "qq_authentication_failed", "QQ Bot 登录失败",
                details={"exception_type": type(exc).__name__},
            ) from exc

    async def send(self, notification: Notification, *, options: dict) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        effective = {**self._options, **deepcopy(options)}
        validate_instance(effective, _OPTIONS_SCHEMA, path=["options"])
        kind, target = effective.get("target_kind"), effective.get("target_id")
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
        await self._send_via_api(
            notification.text,
            kind=address.kind,
            target=address.target,
            message_id=address.message_id,
        )

    async def start_receiving(
        self, handler: InboundHandler, *, temporary: bool = False
    ) -> None:
        del temporary
        self._receiver_state = "connecting"
        self._receiver_error = None
        try:
            await self._start_receiving(handler)
        except asyncio.CancelledError:
            self._receiver_state = "stopped"
            raise
        except Exception as exc:
            self._receiver_state = "failed"
            self._receiver_error = getattr(exc, "code", type(exc).__name__)
            raise

    async def _start_receiving(self, handler: InboundHandler) -> None:
        if self._client is None:
            await self._initialize_client()
        if self._runner is not None:
            raise ChannelDeliveryError("qq_already_receiving", "QQ 渠道已在接收消息")
        self._handler = handler
        if self._gateway_coro is None:
            raise ChannelDeliveryError("qq_sdk_invalid", "qq-botpy 网关协程不可用")
        gateway = self._gateway_coro
        self._gateway_coro = None
        self._runner = asyncio.create_task(gateway, name="qq-botpy")
        self._runner.add_done_callback(self._receiver_done)

    async def stop_receiving(self) -> None:
        runner, self._runner = self._runner, None
        self._handler = None
        if runner is not None:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
            self._client = None
            gateway, self._gateway_coro = self._gateway_coro, None
            if inspect.iscoroutine(gateway):
                gateway.close()
        if self._receiver_state != "failed":
            self._receiver_state = "stopped"

    async def stop(self) -> None:
        self._stopping = True
        await self.stop_receiving()
        self._client = None

    @staticmethod
    def _intents(botpy: Any) -> Any:
        intents_cls = getattr(botpy, "Intents", None)
        if not callable(intents_cls):
            raise ChannelDeliveryError("qq_sdk_invalid", "qq-botpy 缺少 Intents")
        return intents_cls(
            public_messages=True,
            public_guild_messages=True,
            direct_message=True,
        )

    def _make_client_factory(self, botpy: Any) -> Callable[..., Any]:
        parent = botpy.Client
        http_type = getattr(getattr(botpy, "http", None), "BotHttp", None)
        api_type = getattr(getattr(botpy, "api", None), "BotAPI", None)
        if not isinstance(http_type, type) or not isinstance(api_type, type):
            raise ChannelDeliveryError("qq_sdk_invalid", "qq-botpy 缺少公开 HTTP API 注入入口")
        http_module = importlib.import_module("botpy.http")
        gateway_module = importlib.import_module("botpy.gateway")
        from websockets.uri import get_proxy, parse_uri

        emit = self._emit_message
        channel = self

        async def update_access_token(token):
            async with http_module.aiohttp.ClientSession(trust_env=True) as session:
                async with session.post(
                    "https://bots.qq.com/app/getAppAccessToken",
                    timeout=http_module.aiohttp.ClientTimeout(total=channel._timeout),
                    json={"appId": token.app_id, "clientSecret": token.secret},
                ) as response:
                    data = await response.json()
                    status = response.status
            if not isinstance(data, dict) or not data.get("access_token"):
                code = data.get("code") if isinstance(data, dict) else None
                message = (
                    "QQ Bot 凭据无效（100016）：请核对该机器人的 AppID 和当前 Client Secret，"
                    "并确认没有使用已重置的旧密钥"
                    if str(code) == "100016"
                    else "QQ Bot token 请求被平台拒绝"
                )
                raise ChannelDeliveryError(
                    "qq_authentication_rejected", message,
                    details={"http_status": status, "platform_code": code},
                )
            value = data["access_token"]
            try:
                expires_in = int(data["expires_in"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ChannelDeliveryError(
                    "qq_token_invalid", "QQ Bot token 响应缺少有效的到期时间",
                ) from exc
            if status != 200 or not isinstance(value, str) or expires_in <= 0:
                raise ChannelDeliveryError("qq_token_invalid", "QQ Bot token 响应无效")
            token.access_token = value
            token.expires_in = int(time.time()) + expires_in

        class NoPostRetryBotHttp(http_type):
            async def login(self, token):
                # REST and Gateway share this token object; keep its identity
                # so initial authentication and later refresh use one value.
                token.update_access_token = MethodType(update_access_token, token)
                return await super().login(token)

            async def check_session(self):
                # qq-botpy 1.2.1 creates both sessions without trust_env, which
                # makes its REST and Gateway traffic ignore configured proxies.
                await self._token.check_token()
                self._headers = {
                    "Authorization": self._token.get_string(),
                    "X-Union-Appid": self._token.app_id,
                }
                if not self._session or self._session.closed:
                    self._session = http_module.aiohttp.ClientSession(
                        connector=http_module.TCPConnector(
                            limit=500,
                            force_close=True,
                        ),
                        trust_env=True,
                    )

            async def request(self, route: Any, retry_time: int = 0, **kwargs: Any):
                # botpy retries by recursively incrementing retry_time after a reset.
                if route.method == "POST" and retry_time > 0:
                    raise ConnectionResetError("QQ API POST acknowledgement was lost")
                return await super().request(route, retry_time=retry_time, **kwargs)

        class ProxyAwareBotWebSocket(gateway_module.BotWebSocket):
            async def ws_connect(self):
                ws_url = self._session["url"]
                if not ws_url:
                    raise RuntimeError("qq-botpy Gateway URL is empty")

                async with gateway_module.ClientSession(
                    connector=gateway_module.TCPConnector(
                        limit=10,
                    ),
                    trust_env=True,
                ) as session:
                    # aiohttp only checks WSS_PROXY for wss URLs. Reuse the
                    # WebSocket library's HTTPS_PROXY / NO_PROXY selection.
                    async with session.ws_connect(
                        ws_url, proxy=get_proxy(parse_uri(ws_url))
                    ) as ws_conn:
                        while True:
                            msg = await ws_conn.receive()
                            if msg.type == gateway_module.WSMsgType.TEXT:
                                await self.on_message(ws_conn, msg.data)
                            elif msg.type == gateway_module.WSMsgType.ERROR:
                                await self.on_error(ws_conn.exception())
                                await ws_conn.close()
                            elif msg.type in {
                                gateway_module.WSMsgType.CLOSED,
                                gateway_module.WSMsgType.CLOSE,
                            }:
                                await self.on_closed(ws_conn.close_code, msg.extra)
                            if ws_conn.closed:
                                break

        class Client(parent):
            def __init__(self, *, intents: Any):
                real_sdk = parent.__module__.split(".", 1)[0] == "botpy"
                kwargs = {"intents": intents, "log_level": logging.INFO}
                if real_sdk:
                    # botpy's default installs TimedRotatingFileHandler and
                    # writes/flushes it from gateway callbacks.  Let the
                    # application logger own output instead.
                    kwargs.update(bot_log=None, ext_handlers=False)
                super().__init__(**kwargs)
                if real_sdk:
                    logging.getLogger("botpy").propagate = True
                self.http = NoPostRetryBotHttp(
                    timeout=self.http.timeout,
                    is_sandbox=self.http.is_sandbox,
                )
                self.api = api_type(http=self.http)

            async def bot_connect(self, session):
                websocket = ProxyAwareBotWebSocket(session, self._connection)
                try:
                    await websocket.ws_connect()
                except (Exception, KeyboardInterrupt, SystemExit) as exc:
                    await websocket.on_error(exc)

            async def on_ready(self):
                channel._receiver_state = "running"
                await super().on_ready()

            async def on_c2c_message_create(self, message):
                await emit("c2c", message)

            async def on_group_at_message_create(self, message):
                await emit("group", message)

            async def on_at_message_create(self, message):
                await emit("guild", message)

            async def on_direct_message_create(self, message):
                await emit("dm", message)

            async def on_error(self, event_method, *args, **kwargs):
                channel._receiver_error = event_method
                channel._receiver_state = "failed"
                await super().on_error(event_method, *args, **kwargs)

        return Client

    def _receiver_done(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._receiver_state = "failed"
            self._receiver_error = type(error).__name__
            _LOGGER.error(
                "qq_gateway_stopped",
                extra={"error_code": "qq_gateway_failed", "exception_type": type(error).__name__},
            )
        elif self._runner is task and self._receiver_state != "stopped":
            self._receiver_state = "stopped"

    def receiver_status(self) -> dict[str, Any]:
        return {"state": self._receiver_state, "error": self._receiver_error}

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
        sender = _value(author, "user_openid", "member_openid", "id", default=None)
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
        address = ChannelAddress(
            kind=kind,
            target=target,
            sender=sender,
            message_id=message_id,
            conversation_type="private" if kind == "c2c" else "group" if kind == "group" else None,
        )
        await self._handler(InboundMessage(request_id=message_id, text=content.strip(), address=address))

    async def _send_via_api(
        self, text: str, *, kind: str, target: str, message_id: str | None = None
    ) -> None:
        if self._client is None:
            await self._initialize_client()
        api = getattr(self._client, "api", None)
        if api is None:
            raise ChannelDeliveryError("qq_sdk_invalid", "qq-botpy 客户端缺少 API 入口")
        method_names = {
            "c2c": ("post_c2c_message",),
            "group": ("post_group_message",),
            "guild": ("post_message",),
            "dm": ("post_dms",),
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
                result = await result
            message_id = _value(result, "id", "message_id")
            if not isinstance(message_id, str) or not message_id:
                raise ChannelDeliveryError(
                    "qq_send_uncertain", "QQ API 未返回可验证的消息 ID",
                    uncertain=True, details={"kind": kind},
                )
        except ChannelDeliveryError:
            raise
        except Exception as exc:
            raise ChannelDeliveryError(
                "qq_send_failed", "QQ 消息发送失败",
                details={"exception_type": type(exc).__name__, "kind": kind},
                uncertain=not self._is_explicit_rejection(exc),
            ) from exc

    def _is_explicit_rejection(self, error: Exception) -> bool:
        errors = getattr(self._botpy, "errors", None)
        if errors is None:
            return False
        rejection_names = (
            "AuthenticationFailedError",
            "ForbiddenError",
            "NotFoundError",
            "MethodNotAllowedError",
            "SequenceNumberError",
        )
        rejection_types = tuple(
            error_type
            for name in rejection_names
            if isinstance((error_type := getattr(errors, name, None)), type)
        )
        return bool(rejection_types) and isinstance(error, rejection_types)


class QQChannelType:
    name = "qq"
    id_prefix = "qq"
    description = "QQ 官方 Bot 双向消息与通知渠道；首次互动需由用户完成，插件无法自动代替用户发起，发送还受平台权限与会话时效限制"
    capabilities = ["notification", "conversation"]
    options_schema = _OPTIONS_SCHEMA

    def connection_options(self, address: ChannelAddress) -> dict[str, str] | None:
        if (
            address.kind != "c2c"
            or address.conversation_type != "private"
            or not address.sender
        ):
            return None
        return {"target_kind": "c2c", "target_id": address.sender}

    async def create(self, config: ChannelConfig, credentials: Any) -> QQChannel:
        return QQChannel(config, credentials)
