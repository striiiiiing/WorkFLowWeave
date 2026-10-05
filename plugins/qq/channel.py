"""Official QQ Bot channel: REST notifications and Gateway conversations."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx
import websockets
from pydantic import TypeAdapter

from logagent.channel.context import remaining_delivery_time
from logagent.channel.conversation import ChannelAddress, InboundHandler, InboundMessage
from logagent.channel.errors import ChannelDeliveryError
from logagent.errors import LogAgentError
from logagent.models import ChannelConfig, Credential, Notification
from logagent.schema import resource_options_schema, validate_instance, validate_workflow_options

_LOGGER = logging.getLogger(__name__)
_API_BASE = "https://api.sgroup.qq.com"
_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
_TOKEN_REFRESH_MARGIN = 300
_RECONNECT_DELAYS = (1, 2, 5, 10, 30, 60)
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
            "description": "QQ Bot Client Secret 凭据引用或密文",
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
        {
            "if": {"required": ["target_id"]},
            "then": {"required": ["target_kind"]},
        },
        {
            "if": {"required": ["target_kind"]},
            "then": {"required": ["target_id"]},
        },
    ],
}

_EVENT_ROUTES = {
    "C2C_MESSAGE_CREATE": ("c2c", ("user_openid", "id"), None),
    "GROUP_AT_MESSAGE_CREATE": ("group", ("member_openid", "id"), "group_openid"),
    "AT_MESSAGE_CREATE": ("guild", ("id",), "channel_id"),
    "DIRECT_MESSAGE_CREATE": ("dm", ("id",), "guild_id"),
}
_INTENTS = (1 << 30) | (1 << 12) | (1 << 25) | (1 << 26)
_CREDENTIAL_ADAPTER = TypeAdapter(Credential)


def _encoded(value: str) -> str:
    return quote(value, safe="")


def _message_path(kind: str, target: str) -> str:
    target = _encoded(target)
    paths = {
        "c2c": f"/v2/users/{target}/messages",
        "group": f"/v2/groups/{target}/messages",
        "guild": f"/channels/{target}/messages",
        "dm": f"/dms/{target}/messages",
    }
    try:
        return paths[kind]
    except KeyError as exc:
        raise ChannelDeliveryError(
            "qq_address_invalid",
            "QQ 消息地址类型不受支持",
            details={"kind": kind},
        ) from exc


class QQChannel:
    """Resident official QQ Bot adapter with separately controlled receiving."""

    def __init__(
        self,
        config: ChannelConfig,
        credentials: Any,
        *,
        http_transport: httpx.AsyncBaseTransport | None = None,
        websocket_connect: Callable[..., Awaitable[Any]] | None = None,
        api_base: str = _API_BASE,
        token_url: str = _TOKEN_URL,
    ):
        validate_instance(
            config.options, resource_options_schema(_OPTIONS_SCHEMA), path=["options"]
        )
        self._options = dict(config.options)
        self._credentials = credentials
        self._http_transport = http_transport
        self._websocket_connect = websocket_connect or websockets.connect
        self._api_base = api_base.rstrip("/")
        self._token_url = token_url
        self._timeout = config.timeout
        self._http: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._receiving = False
        self._stopping = False
        self._handler: InboundHandler | None = None
        self._receiver_task: asyncio.Task[None] | None = None
        self._websocket: Any = None
        self._handler_tasks: set[asyncio.Task[None]] = set()
        self._session_id: str | None = None
        self._bot_user_id: str | None = None
        self._sequence: int | None = None
        self._message_sequences: dict[str, int] = {}
        self._start_lock = asyncio.Lock()
        self._receiver_state = "stopped"
        self._receiver_error: dict[str, str] | None = None
        self._reconnect_attempts = 0

    def receiver_status(self) -> dict[str, Any]:
        """Return transport state without exposing platform data or credentials."""
        return {
            "state": self._receiver_state,
            "error": dict(self._receiver_error) if self._receiver_error else None,
            "reconnect_attempts": self._reconnect_attempts,
            "active_handlers": len(self._handler_tasks),
        }

    async def start(self) -> None:
        async with self._start_lock:
            if self._stopping:
                raise ChannelDeliveryError("qq_closed", "QQ 渠道已关闭")
            if self._http is None:
                self._http = httpx.AsyncClient(
                    transport=self._http_transport, timeout=self._timeout
                )

    async def stop(self) -> None:
        await self.stop_receiving()
        async with self._start_lock:
            if self._http is not None:
                await self._http.aclose()
                self._http = None
            self._stopping = True

    async def send(self, notification: Notification, *, options: dict) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        kind = self._options.get("target_kind")
        target = self._options.get("target_id")
        if not kind or not target:
            raise ChannelDeliveryError(
                "qq_target_missing", "QQ 普通发送需要在渠道配置中设置 target_kind 和 target_id"
            )
        await self._send_to(notification, kind=kind, target=target, message_id=None)

    async def reply(
        self,
        notification: Notification,
        *,
        address: ChannelAddress,
        options: dict,
    ) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        if address.kind == "test":
            raise ChannelDeliveryError("qq_address_invalid", "QQ 渠道不能回复测试地址")
        await self._send_to(
            notification,
            kind=address.kind,
            target=address.target,
            message_id=address.message_id,
        )

    async def start_receiving(self, handler: InboundHandler) -> None:
        if self._stopping:
            raise ChannelDeliveryError("qq_closed", "QQ 渠道已关闭")
        if self._http is None:
            raise ChannelDeliveryError("qq_not_started", "QQ 渠道尚未启动")
        if self._receiving:
            raise ChannelDeliveryError("qq_already_receiving", "QQ 渠道已在接收消息")
        self._handler = handler
        self._receiver_state = "connecting"
        try:
            token = await self._get_token()
            websocket = await self._connect_gateway(token)
        except Exception as exc:
            self._receiver_state = "failed"
            self._receiver_error = {
                "code": getattr(exc, "code", "qq_gateway_connect_failed"),
                "exception_type": type(exc).__name__,
            }
            self._handler = None
            raise
        self._websocket = websocket
        self._receiving = True
        self._receiver_error = None
        self._reconnect_attempts = 0
        self._receiver_task = asyncio.create_task(
            self._receive_forever(websocket), name="qq-gateway-receiver"
        )
        self._receiver_task.add_done_callback(self._receiver_done)

    async def stop_receiving(self) -> None:
        if not self._receiving and self._receiver_task is None:
            return
        self._receiving = False
        self._receiver_state = "stopping"
        websocket, self._websocket = self._websocket, None
        task, self._receiver_task = self._receiver_task, None
        try:
            if websocket is not None:
                await websocket.close()
        finally:
            try:
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            finally:
                try:
                    handler_tasks = tuple(self._handler_tasks)
                    for handler_task in handler_tasks:
                        handler_task.cancel()
                    if handler_tasks:
                        await asyncio.gather(*handler_tasks, return_exceptions=True)
                finally:
                    self._handler = None
                    self._receiver_state = "stopped"

    async def _get_token(self, *, force: bool = False) -> str:
        async with self._token_lock:
            if (
                not force
                and self._token
                and time.monotonic() < self._token_expires_at - _TOKEN_REFRESH_MARGIN
            ):
                return self._token
            if self._http is None:
                raise ChannelDeliveryError("qq_not_started", "QQ 渠道尚未启动")
            secret_value = self._options["client_secret"]
            if self._credentials is None:
                raise ChannelDeliveryError("credential_resolver_missing", "QQ 凭据解析器未配置")
            try:
                credential = _CREDENTIAL_ADAPTER.validate_python(secret_value)
                secret = await self._credentials.resolve(credential)
                response = await self._http.post(
                    self._token_url,
                    json={
                        "appId": self._options["app_id"],
                        "clientSecret": secret,
                    },
                    timeout=remaining_delivery_time(self._timeout),
                )
                response.raise_for_status()
                payload = response.json()
                token = payload["access_token"]
                expires_in = float(payload["expires_in"])
                if (
                    not isinstance(token, str)
                    or not token
                    or not math.isfinite(expires_in)
                    or expires_in <= 0
                ):
                    raise ValueError("invalid token response")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise ChannelDeliveryError(
                    "qq_authentication_failed",
                    "QQ Bot 凭据解析或令牌请求失败",
                    details={"exception_type": type(exc).__name__},
                ) from exc
            self._token = token
            self._token_expires_at = time.monotonic() + expires_in
            return token

    async def _connect_gateway(self, token: str) -> Any:
        if self._http is None:
            raise ChannelDeliveryError("qq_not_started", "QQ 渠道尚未启动")
        try:
            response = await self._http.get(
                f"{self._api_base}/gateway",
                headers={"Authorization": f"QQBot {token}"},
            )
            response.raise_for_status()
            gateway_url = response.json()["url"]
            if not isinstance(gateway_url, str) or not gateway_url.startswith("wss://"):
                raise ValueError("invalid gateway URL")
            return await self._websocket_connect(gateway_url)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ChannelDeliveryError(
                "qq_gateway_connect_failed",
                "无法获取 QQ Gateway 或建立 WebSocket 连接",
                details={"exception_type": type(exc).__name__},
            ) from exc

    async def _send_to(
        self,
        notification: Notification,
        *,
        kind: str,
        target: str,
        message_id: str | None,
    ) -> None:
        if not notification.text:
            raise ChannelDeliveryError("qq_message_empty", "QQ 消息内容不能为空")
        if self._http is None:
            raise ChannelDeliveryError("qq_not_started", "QQ 渠道尚未启动")
        path = _message_path(kind, target)
        request_started = False
        try:
            budget = remaining_delivery_time(self._timeout)
            if budget <= 0:
                raise TimeoutError("delivery budget exhausted before send")
            async with asyncio.timeout(budget):
                token = await self._get_token()
                async with self._send_lock:
                    body: dict[str, Any] = {"content": notification.text}
                    if message_id:
                        body["msg_id"] = message_id
                    sequence_key = message_id or f"{kind}:{target}"
                    if kind in {"c2c", "group"}:
                        sequence = self._message_sequences.get(sequence_key, 0) + 1
                        self._message_sequences[sequence_key] = sequence
                        body.update({"msg_type": 0, "msg_seq": sequence})
                    request_started = True
                    response = await self._http.post(
                        f"{self._api_base}{path}",
                        headers={"Authorization": f"QQBot {token}"},
                        json=body,
                        timeout=remaining_delivery_time(self._timeout),
                    )
                    response.raise_for_status()
                    try:
                        receipt = response.json()
                    except ValueError as exc:
                        raise ChannelDeliveryError(
                            "qq_send_uncertain",
                            "QQ API 未返回可验证的消息回执",
                            uncertain=True,
                            details={"response": "invalid_json", "kind": kind},
                        ) from exc
                    if (
                        not isinstance(receipt, dict)
                        or not isinstance(receipt.get("id"), str)
                        or not receipt["id"]
                    ):
                        raise ChannelDeliveryError(
                            "qq_send_uncertain",
                            "QQ API 响应缺少消息 ID，是否受理不确定",
                            uncertain=True,
                            details={"kind": kind},
                        )
        except asyncio.CancelledError:
            raise
        except ChannelDeliveryError:
            raise
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise ChannelDeliveryError(
                "qq_send_rejected" if status < 500 else "qq_send_uncertain",
                "QQ API 拒绝了消息"
                if status < 500
                else "QQ API 返回服务端错误，消息是否受理不确定",
                uncertain=status >= 500,
                details={"status": status, "kind": kind},
            ) from exc
        except TimeoutError as exc:
            raise ChannelDeliveryError(
                "qq_send_uncertain" if request_started else "qq_send_timeout",
                "QQ 发送超时，消息是否受理不确定" if request_started else "QQ 发送超出剩余投递时限",
                uncertain=request_started,
                details={"kind": kind},
            ) from exc
        except httpx.ConnectError as exc:
            raise ChannelDeliveryError(
                "qq_send_failed",
                "无法连接 QQ API",
                details={"exception_type": type(exc).__name__, "kind": kind},
            ) from exc
        except httpx.TransportError as exc:
            raise ChannelDeliveryError(
                "qq_send_uncertain",
                "QQ 网络传输中断，消息是否受理不确定",
                uncertain=True,
                details={"exception_type": type(exc).__name__, "kind": kind},
            ) from exc
        except Exception as exc:
            raise ChannelDeliveryError(
                "qq_send_failed",
                "QQ 消息发送失败",
                details={"exception_type": type(exc).__name__, "kind": kind},
            ) from exc

    async def _receive_forever(self, websocket: Any) -> None:
        backoff_index = 0
        while self._receiving:
            try:
                await self._serve_gateway(websocket)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                code = getattr(exc, "code", "qq_gateway_connection_failed")
                _LOGGER.warning(
                    "qq_gateway_connection_failed",
                    extra={"error_code": code, "exception_type": type(exc).__name__},
                )
                self._receiver_error = {
                    "code": code,
                    "exception_type": type(exc).__name__,
                }
                self._receiver_state = "reconnecting"
            finally:
                if self._websocket is websocket:
                    self._websocket = None
                await websocket.close()
            if not self._receiving:
                return
            self._receiver_state = "reconnecting"
            while self._receiving:
                await asyncio.sleep(
                    _RECONNECT_DELAYS[min(backoff_index, len(_RECONNECT_DELAYS) - 1)]
                )
                backoff_index += 1
                self._reconnect_attempts = backoff_index
                try:
                    token = await self._get_token(
                        force=time.monotonic() >= self._token_expires_at - _TOKEN_REFRESH_MARGIN
                    )
                    websocket = await self._connect_gateway(token)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    code = getattr(exc, "code", "qq_gateway_reconnect_failed")
                    _LOGGER.warning(
                        "qq_gateway_reconnect_failed",
                        extra={
                            "error_code": code,
                            "exception_type": type(exc).__name__,
                        },
                    )
                    self._receiver_error = {
                        "code": code,
                        "exception_type": type(exc).__name__,
                    }
                    self._receiver_state = "reconnecting"
                    continue
                self._websocket = websocket
                break

    async def _serve_gateway(self, websocket: Any) -> None:
        heartbeat_task: asyncio.Task[None] | None = None
        receive_task: asyncio.Task[Any] | None = None
        heartbeat_ack = asyncio.Event()
        heartbeat_ack.set()
        try:
            while True:
                receive_task = asyncio.create_task(websocket.recv())
                if heartbeat_task is None:
                    raw = await receive_task
                else:
                    done, _ = await asyncio.wait(
                        {receive_task, heartbeat_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if heartbeat_task in done:
                        heartbeat_task.result()
                    raw = receive_task.result()
                receive_task = None
                try:
                    payload = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    raise ChannelDeliveryError(
                        "qq_gateway_protocol_error", "QQ Gateway 返回无效 JSON"
                    ) from None
                if not isinstance(payload, dict) or "op" not in payload:
                    raise ChannelDeliveryError(
                        "qq_gateway_protocol_error", "QQ Gateway 帧缺少操作码"
                    )
                if isinstance(payload.get("s"), int):
                    self._sequence = payload["s"]
                op = payload["op"]
                if op == 10:
                    self._receiver_state = "connected"
                    data = payload.get("d") or {}
                    heartbeat_task = asyncio.create_task(
                        self._heartbeat(websocket, data.get("heartbeat_interval"), heartbeat_ack)
                    )
                    await self._identify_or_resume(websocket)
                elif op == 0:
                    event_name = payload.get("t")
                    data = payload.get("d") or {}
                    if event_name == "READY":
                        self._session_id = data.get("session_id")
                        user = data.get("user")
                        user_id = user.get("id") if isinstance(user, dict) else None
                        self._bot_user_id = (
                            user_id if isinstance(user_id, str) and user_id else None
                        )
                        self._receiver_state = "running"
                        self._receiver_error = None
                        self._reconnect_attempts = 0
                    elif event_name == "RESUMED":
                        self._receiver_state = "running"
                        self._receiver_error = None
                        self._reconnect_attempts = 0
                        continue
                    elif event_name in _EVENT_ROUTES:
                        self._dispatch_message(event_name, data)
                elif op == 7:
                    self._receiver_state = "reconnecting"
                    return
                elif op == 9:
                    if not payload.get("d"):
                        self._session_id = None
                        self._bot_user_id = None
                        self._sequence = None
                    self._receiver_state = "reconnecting"
                    return
                elif op == 11:
                    heartbeat_ack.set()
        finally:
            if receive_task is not None and not receive_task.done():
                receive_task.cancel()
                await asyncio.gather(receive_task, return_exceptions=True)
            if heartbeat_task is not None:
                heartbeat_finished = heartbeat_task.done()
                if not heartbeat_finished:
                    heartbeat_task.cancel()
                result = await asyncio.gather(heartbeat_task, return_exceptions=True)
                heartbeat_error = result[0]
                if heartbeat_finished and isinstance(heartbeat_error, BaseException):
                    if not isinstance(heartbeat_error, asyncio.CancelledError):
                        raise heartbeat_error

    async def _identify_or_resume(self, websocket: Any) -> None:
        if self._session_id and self._sequence is not None:
            payload = {
                "op": 6,
                "d": {
                    "token": f"QQBot {await self._get_token()}",
                    "session_id": self._session_id,
                    "seq": self._sequence,
                },
            }
        else:
            payload = {
                "op": 2,
                "d": {
                    "token": f"QQBot {await self._get_token()}",
                    "intents": _INTENTS,
                    "shard": [0, 1],
                },
            }
        await websocket.send(json.dumps(payload, separators=(",", ":")))

    async def _heartbeat(
        self, websocket: Any, interval_ms: Any, acknowledged: asyncio.Event
    ) -> None:
        try:
            interval_value = float(interval_ms)
            if not math.isfinite(interval_value) or interval_value <= 0:
                raise ValueError("invalid heartbeat interval")
            interval = interval_value / 1000
        except (TypeError, ValueError):
            raise ChannelDeliveryError(
                "qq_gateway_protocol_error", "QQ Gateway 心跳间隔无效"
            ) from None
        while self._receiving:
            await asyncio.sleep(interval)
            if not acknowledged.is_set():
                raise ChannelDeliveryError("qq_heartbeat_ack_timeout", "QQ Gateway 心跳缺少 ACK")
            acknowledged.clear()
            await websocket.send(json.dumps({"op": 1, "d": self._sequence}, separators=(",", ":")))

    def _dispatch_message(self, event_name: str, data: dict[str, Any]) -> None:
        message_id = data.get("id")
        if not isinstance(message_id, str) or not message_id:
            _LOGGER.warning("Ignoring QQ message event without message ID: %s", event_name)
            return
        kind, sender_keys, target_key = _EVENT_ROUTES[event_name]
        author = data.get("author") or {}
        sender = next((author.get(key) for key in sender_keys if author.get(key)), None)
        target = data.get(target_key) if target_key else sender
        text = data.get("content")
        if not isinstance(sender, str) or not sender or not isinstance(target, str) or not target:
            _LOGGER.warning("Ignoring malformed QQ message event: %s", event_name)
            return
        if not isinstance(text, str) or not text.strip():
            return
        if kind == "guild" and self._bot_user_id:
            mention_prefix = re.compile(
                rf"^\s*<@!?{re.escape(self._bot_user_id)}>\s*"
            )
            text = mention_prefix.sub("", text, count=1)
            if not text.strip():
                return
        try:
            message = InboundMessage(
                request_id=message_id,
                text=text.strip(),
                address=ChannelAddress(
                    kind=kind, target=target, sender=sender, message_id=message_id
                ),
            )
        except ValueError:
            _LOGGER.warning(
                "qq_inbound_message_invalid",
                extra={
                    "event_type": event_name,
                    "exception_type": "ValidationError",
                },
            )
            return
        if self._handler is None:
            _LOGGER.error("QQ message received without an inbound handler")
            return
        task = asyncio.create_task(self._invoke_handler(message), name=f"qq-handler-{message_id}")
        self._handler_tasks.add(task)
        task.add_done_callback(self._handler_done)

    async def _invoke_handler(self, message: InboundMessage) -> None:
        if self._handler is not None:
            try:
                await self._handler(message)
            except LogAgentError as exc:
                if exc.code != "channel_queue_full":
                    raise
                _LOGGER.warning("qq_inbound_queue_full", extra={
                    "event": "qq_inbound_queue_full", "error_code": exc.code,
                })
                try:
                    await self.reply(
                        Notification(
                            session_id="channel_queue", output_id="channel_error",
                            text="当前对话消息过多，请稍后重试。",
                        ),
                        address=message.address, options={},
                    )
                except Exception:
                    _LOGGER.exception("qq_queue_rejection_reply_failed")

    def _handler_done(self, task: asyncio.Task[None]) -> None:
        self._handler_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            _LOGGER.error(
                "qq_inbound_handler_failed",
                extra={
                    "error_code": getattr(error, "code", "qq_inbound_handler_failed"),
                    "exception_type": type(error).__name__,
                },
            )

    def _receiver_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._receiver_state = "failed"
            self._receiver_error = {
                "code": getattr(error, "code", "qq_receiver_failed"),
                "exception_type": type(error).__name__,
            }
            _LOGGER.error(
                "qq_receiver_stopped_unexpectedly",
                extra={
                    "error_code": self._receiver_error["code"],
                    "exception_type": type(error).__name__,
                },
            )


class QQChannelType:
    name = "qq"
    id_prefix = "qq"
    description = "QQ 官方 Bot 双向消息与通知渠道"
    capabilities = ["notification", "conversation"]
    options_schema = _OPTIONS_SCHEMA

    async def create(self, config: ChannelConfig, credentials: Any) -> QQChannel:
        return QQChannel(config, credentials)
