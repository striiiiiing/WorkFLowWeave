"""Feishu channel backed by the official ``lark-oapi`` SDK.

The pinned SDK exposes a synchronous WebSocket start method around a private
async loop. This adapter drives that loop on a shared, managed thread. SDK
callbacks normalize events and wait for Manager admission; they never run an
Agent turn themselves.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import TimeoutError as FutureTimeoutError
from copy import deepcopy
from typing import Any

from pydantic import TypeAdapter

from logagent.channel.context import remaining_delivery_time
from logagent.channel.conversation import ChannelAddress, InboundHandler, InboundMessage
from logagent.channel.errors import ChannelDeliveryError
from logagent.models import ChannelConfig, Credential, Notification
from logagent.schema import (
    resource_options_schema,
    validate_instance,
    validate_workflow_options,
)

_LOGGER = logging.getLogger(__name__)
_RUNTIME_STOP_TIMEOUT = 5.0
_EVENT_ADMISSION_TIMEOUT = 30.0
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
            "description": "飞书应用 App ID",
        },
        "app_secret": {
            "description": "飞书应用 App Secret 凭据引用",
            "anyOf": [_CREDENTIAL_SCHEMA, {"type": "null"}],
            "x-logagent-credential": True,
        },
        "target_kind": {
            "type": "string",
            "enum": ["chat_id", "open_id", "user_id", "email"],
            "description": "单向通知接收者类型",
        },
        "target_id": {
            "type": "string",
            "minLength": 1,
            "pattern": r"^\S+$",
            "description": "单向通知接收者标识",
            "x-logagent-workflow": True,
        },
        "receive_events": {
            "type": "boolean",
            "description": "是否接收飞书文本消息事件",
            "default": True,
        },
    },
    "required": ["app_id", "app_secret"],
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
_CREDENTIAL_ADAPTER = TypeAdapter(Credential)


def _attr(value: Any, *names: str, default: Any = None) -> Any:
    """Read an SDK model or mapping without exposing SDK types to the core."""

    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        result = getattr(value, name, None)
        if result is not None:
            return result
    return default


def _response_ok(response: Any) -> bool:
    success = getattr(response, "success", None)
    if success is not None:
        return bool(success() if callable(success) else success)
    code = _attr(response, "code")
    return code in (0, "0")


class _SDKLoopRuntime:
    """Run the SDK module's private loop on one shared background thread."""

    def __init__(self, sdk_module: Any) -> None:
        self._loop = asyncio.new_event_loop()
        self._sdk_module = sdk_module
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="feishu-sdk-websocket",
            daemon=True,
        )
        self._references = 0
        self._stopping = False
        self._closed = False
        self._thread.start()
        self._ready.wait()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    @property
    def references(self) -> int:
        return self._references

    @property
    def stopping(self) -> bool:
        return self._stopping

    def acquire(self) -> None:
        if self._stopping or self._closed:
            raise RuntimeError("Feishu SDK loop is stopping")
        self._references += 1

    def release_reference(self) -> bool:
        if self._references <= 0:
            raise RuntimeError("Feishu SDK loop reference count is invalid")
        self._references -= 1
        if self._references:
            return False
        self._stopping = True
        return True

    def stop_and_join(self) -> None:
        if self._closed:
            return

        async def assert_no_tasks() -> None:
            current = asyncio.current_task()
            pending = [task for task in asyncio.all_tasks() if task is not current]
            if pending:
                raise RuntimeError(f"Feishu SDK loop has {len(pending)} pending tasks")

        if self._loop.is_running():
            asyncio.run_coroutine_threadsafe(assert_no_tasks(), self._loop).result(
                timeout=_RUNTIME_STOP_TIMEOUT
            )
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(_RUNTIME_STOP_TIMEOUT)
        if self._thread.is_alive():
            raise TimeoutError("Feishu SDK loop thread did not stop")
        self._loop.close()
        self._closed = True

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._sdk_module.loop = self._loop
        self._ready.set()
        self._loop.run_forever()

    async def call(self, operation):
        future = asyncio.run_coroutine_threadsafe(operation, self._loop)
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            future.cancel()
            raise


_SDK_RUNTIMES: dict[Any, _SDKLoopRuntime] = {}
_SDK_RUNTIMES_LOCK = threading.Lock()


def _acquire_runtime_for_module(sdk_module: Any) -> _SDKLoopRuntime:
    with _SDK_RUNTIMES_LOCK:
        runtime = _SDK_RUNTIMES.get(sdk_module)
        if runtime is None:
            runtime = _SDKLoopRuntime(sdk_module)
            _SDK_RUNTIMES[sdk_module] = runtime
        if runtime.stopping:
            raise RuntimeError("Feishu SDK loop cleanup has not completed")
        runtime.acquire()
        return runtime


def _release_runtime(runtime: _SDKLoopRuntime) -> None:
    with _SDK_RUNTIMES_LOCK:
        if _SDK_RUNTIMES.get(runtime._sdk_module) is not runtime:
            if runtime._closed:
                return
            raise RuntimeError("Feishu SDK loop registration changed during cleanup")
        if runtime.references:
            if not runtime.release_reference():
                return
        elif not runtime.stopping:
            raise RuntimeError("Feishu SDK loop reference count is invalid")
        runtime.stop_and_join()
        del _SDK_RUNTIMES[runtime._sdk_module]


async def _finish_thread_task(task: asyncio.Task[Any]) -> Any:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


async def _release_runtime_async(runtime: _SDKLoopRuntime) -> None:
    task = asyncio.create_task(asyncio.to_thread(_release_runtime, runtime))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await _finish_thread_task(task)
        raise


async def _acquire_runtime(factory: Any) -> _SDKLoopRuntime:
    module_name = getattr(factory, "__module__", None)
    if not module_name:
        raise ChannelDeliveryError("feishu_sdk_incompatible", "无法定位飞书 WebSocket SDK 模块")
    module = await asyncio.to_thread(importlib.import_module, module_name)
    task = asyncio.create_task(asyncio.to_thread(_acquire_runtime_for_module, module))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            runtime = await _finish_thread_task(task)
        except BaseException:
            raise
        cleanup = asyncio.create_task(asyncio.to_thread(_release_runtime, runtime))
        await _finish_thread_task(cleanup)
        raise
    except RuntimeError as exc:
        raise ChannelDeliveryError(
            "feishu_sdk_loop_unavailable",
            "飞书 WebSocket 运行时正在清理",
            details={"exception_type": type(exc).__name__},
        ) from None


def _task_uses_client(task: asyncio.Task[Any], client: Any) -> bool:
    coroutine = task.get_coro()
    frame = getattr(coroutine, "cr_frame", None)
    return frame is not None and frame.f_locals.get("self") is client


async def _start_sdk_receiver(
    factory: Any,
    app_id: str,
    secret: str,
    dispatcher: Any,
    receiver_done: Callable[[asyncio.Task[Any]], None],
    receiver_created: Callable[[Any], None],
):
    client = factory(app_id, secret, event_handler=dispatcher)
    receiver_created(client)
    connect = getattr(client, "_connect", None)
    disconnect = getattr(client, "_disconnect", None)
    ping_loop = getattr(client, "_ping_loop", None)
    if not all(callable(method) for method in (connect, disconnect, ping_loop)):
        raise ChannelDeliveryError(
            "feishu_sdk_incompatible",
            "当前 lark-oapi 版本缺少可管理的 WebSocket 生命周期接口",
        )

    async def tracked_connect() -> None:
        existing = asyncio.all_tasks()
        await connect()
        receiver_tasks = [
            task
            for task in asyncio.all_tasks() - existing
            if _task_uses_client(task, client)
            and task.get_coro().__name__ == "_receive_message_loop"
        ]
        for task in receiver_tasks:
            task.add_done_callback(receiver_done)

    client._connect = tracked_connect
    try:
        await tracked_connect()
        if getattr(client, "_conn", None) is None:
            raise ChannelDeliveryError("feishu_connect_failed", "飞书 WebSocket 未建立连接")
        asyncio.create_task(ping_loop(), name="feishu-websocket-ping")
    except BaseException as start_error:
        try:
            await _stop_sdk_receiver(client)
        except Exception as cleanup_error:
            raise ChannelDeliveryError(
                "feishu_receiver_cleanup_failed",
                "飞书接收启动失败后的连接清理失败",
                details={
                    "start_exception_type": type(start_error).__name__,
                    "cleanup_exception_type": type(cleanup_error).__name__,
                },
            ) from None
        if isinstance(start_error, asyncio.CancelledError):
            raise
        if isinstance(start_error, ChannelDeliveryError):
            raise
        raise ChannelDeliveryError(
            "feishu_receiver_start_failed",
            "飞书 WebSocket 启动失败",
            details={"exception_type": type(start_error).__name__},
        ) from None
    return client


async def _stop_sdk_receiver(client: Any) -> None:
    client._auto_reconnect = False
    try:
        await client._disconnect()
    finally:
        # The pinned SDK cache owns a cleanup coroutine separate from Client.
        # Its destructor alone cannot retire that task before closing the loop.
        cache_task = getattr(getattr(client, "_cache", None), "_cron", None)
        tasks = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and (_task_uses_client(task, client) or task is cache_task)
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class FeishuChannel:
    def __init__(
        self,
        config: ChannelConfig,
        credentials: Any,
        *,
        sdk: Any = None,
        client_factory: Callable[..., Any] | None = None,
        websocket_factory: Callable[..., Any] | None = None,
    ) -> None:
        validate_instance(
            config.options, resource_options_schema(_OPTIONS_SCHEMA), path=["options"]
        )
        self._account_options = dict(config.options)
        self._workflow_options = {}
        self._config = config
        self._credentials = credentials
        self._sdk = sdk
        self._client_factory = client_factory
        self._websocket_factory = websocket_factory
        self._client: Any = None
        self._websocket: Any = None
        self._runtime: _SDKLoopRuntime | None = None
        self._handler: InboundHandler | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._send_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._stop_task: asyncio.Task[None] | None = None
        self._receiving = False

    async def _load_sdk(self) -> Any:
        if self._sdk is not None:
            return self._sdk
        try:
            lark = await asyncio.to_thread(importlib.import_module, "lark_oapi")
        except ImportError as exc:
            raise ChannelDeliveryError(
                "feishu_dependency_missing",
                "飞书渠道需要安装 lark-oapi",
                details={"dependency": "lark-oapi"},
            ) from exc
        self._sdk = lark
        return lark

    async def start(self) -> None:
        async with self._start_lock:
            if self._stop_task is not None:
                raise ChannelDeliveryError("feishu_closed", "飞书渠道已关闭")
            if self._client is not None:
                return
            sdk = await self._load_sdk()
            if self._credentials is None:
                raise ChannelDeliveryError("credential_resolver_missing", "飞书凭据解析器未配置")
            try:
                secret_ref = _CREDENTIAL_ADAPTER.validate_python(
                    self._account_options["app_secret"]
                )
                secret = await self._credentials.resolve(secret_ref)
                if not isinstance(secret, str) or not secret:
                    raise ValueError("empty app secret")
                factory = self._client_factory
                if factory is None:
                    self._client = (
                        sdk.Client.builder()
                        .app_id(self._account_options["app_id"])
                        .app_secret(secret)
                        .build()
                    )
                else:
                    self._client = factory(
                        app_id=self._account_options["app_id"],
                        app_secret=secret,
                    )
            except ChannelDeliveryError:
                raise
            except Exception as exc:
                raise ChannelDeliveryError(
                    "feishu_client_init_failed",
                    "飞书 SDK 客户端初始化失败",
                    details={"exception_type": type(exc).__name__},
                ) from exc

    async def stop(self) -> None:
        previous_stop_failed = (
            self._stop_task is not None
            and self._stop_task.done()
            and (self._stop_task.cancelled() or self._stop_task.exception() is not None)
        )
        if self._stop_task is None or previous_stop_failed:
            self._stop_task = asyncio.create_task(self._close(), name="feishu-close")
        await asyncio.shield(self._stop_task)

    async def _close(self) -> None:
        try:
            await self.stop_receiving()
        finally:
            self._client = None

    @staticmethod
    def _message_models(sdk: Any) -> tuple[Any, Any, Any, Any]:
        try:
            model = sdk.api.im.v1.model
            return (
                model.CreateMessageRequest,
                model.CreateMessageRequestBody,
                model.ReplyMessageRequest,
                model.ReplyMessageRequestBody,
            )
        except AttributeError:
            try:
                from lark_oapi.api.im.v1 import (  # type: ignore[import-not-found]
                    CreateMessageRequest,
                    CreateMessageRequestBody,
                    ReplyMessageRequest,
                    ReplyMessageRequestBody,
                )
            except ImportError as exc:
                raise ChannelDeliveryError(
                    "feishu_sdk_incompatible",
                    "当前 lark-oapi 版本缺少消息请求模型",
                    details={"exception_type": type(exc).__name__},
                ) from exc
            return (
                CreateMessageRequest,
                CreateMessageRequestBody,
                ReplyMessageRequest,
                ReplyMessageRequestBody,
            )

    def _build_message_request(self, *, kind: str, target: str, text: str) -> Any:
        try:
            CreateMessageRequest, CreateMessageRequestBody, _, _ = self._message_models(self._sdk)
            content = json.dumps({"text": text}, ensure_ascii=False)
            body = (
                CreateMessageRequestBody.builder()
                .receive_id(target)
                .msg_type("text")
                .content(content)
                .build()
            )
            return CreateMessageRequest.builder().receive_id_type(kind).request_body(body).build()
        except Exception as exc:
            raise ChannelDeliveryError(
                "feishu_sdk_incompatible",
                "当前 lark-oapi 版本不支持消息发送 API",
                details={"exception_type": type(exc).__name__},
            ) from exc

    def _build_reply_request(self, *, message_id: str, text: str) -> Any:
        try:
            _, _, ReplyMessageRequest, ReplyMessageRequestBody = self._message_models(self._sdk)
            content = json.dumps({"text": text}, ensure_ascii=False)
            body = ReplyMessageRequestBody.builder().msg_type("text").content(content).build()
            return ReplyMessageRequest.builder().message_id(message_id).request_body(body).build()
        except Exception as exc:
            raise ChannelDeliveryError(
                "feishu_sdk_incompatible",
                "当前 lark-oapi 版本不支持消息回复 API",
                details={"exception_type": type(exc).__name__},
            ) from exc

    async def _send_to(self, notification: Notification, *, kind: str, target: str) -> None:
        if not notification.text:
            raise ChannelDeliveryError("feishu_message_empty", "飞书消息内容不能为空")
        if self._client is None:
            raise ChannelDeliveryError("feishu_not_started", "飞书渠道尚未启动")
        request = self._build_message_request(kind=kind, target=target, text=notification.text)
        try:
            async with asyncio.timeout(remaining_delivery_time(self._config.timeout)):
                async with self._send_lock:
                    response = await self._client.im.v1.message.acreate(request)
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise ChannelDeliveryError(
                "feishu_delivery_timeout",
                "飞书发送超时，无法确认消息是否已接受",
                uncertain=True,
            ) from exc
        except Exception as exc:
            raise ChannelDeliveryError(
                "feishu_delivery_failed",
                "飞书消息发送失败",
                uncertain=True,
                details={"exception_type": type(exc).__name__},
            ) from exc
        if not _response_ok(response):
            raise ChannelDeliveryError(
                "feishu_delivery_rejected",
                "飞书 API 拒绝消息",
                details={"code": str(_attr(response, "code", default="unknown"))},
            )

    async def _reply_to(self, notification: Notification, *, message_id: str) -> None:
        if not notification.text:
            raise ChannelDeliveryError("feishu_message_empty", "飞书消息内容不能为空")
        if self._client is None:
            raise ChannelDeliveryError("feishu_not_started", "飞书渠道尚未启动")
        request = self._build_reply_request(message_id=message_id, text=notification.text)
        try:
            async with asyncio.timeout(remaining_delivery_time(self._config.timeout)):
                async with self._send_lock:
                    response = await self._client.im.v1.message.areply(request)
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise ChannelDeliveryError(
                "feishu_delivery_timeout",
                "飞书发送超时，无法确认消息是否已接受",
                uncertain=True,
            ) from exc
        except Exception as exc:
            raise ChannelDeliveryError(
                "feishu_delivery_failed",
                "飞书消息发送失败",
                uncertain=True,
                details={"exception_type": type(exc).__name__},
            ) from exc
        if not _response_ok(response):
            raise ChannelDeliveryError(
                "feishu_delivery_rejected",
                "飞书 API 拒绝消息",
                details={"code": str(_attr(response, "code", default="unknown"))},
            )

    async def send(self, notification: Notification, *, options: dict) -> None:
        validate_workflow_options(options, _OPTIONS_SCHEMA)
        effective = {**self._account_options, **deepcopy(options)}
        validate_instance(effective, _OPTIONS_SCHEMA, path=["options"])
        kind, target = effective.get("target_kind"), effective.get("target_id")
        if not kind or not target:
            raise ChannelDeliveryError(
                "feishu_target_missing", "飞书普通发送需要设置 target_kind 和 target_id"
            )
        await self._send_to(notification, kind=kind, target=target)

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
        if not address.message_id:
            raise ChannelDeliveryError("feishu_message_id_missing", "飞书回复缺少原消息 ID")
        await self._reply_to(notification, message_id=address.message_id)

    async def start_receiving(self, handler: InboundHandler) -> None:
        if self._stop_task is not None:
            raise ChannelDeliveryError("feishu_closed", "飞书渠道已关闭")
        if self._client is None:
            raise ChannelDeliveryError("feishu_not_started", "飞书渠道尚未启动")
        if self._receiving:
            raise ChannelDeliveryError("feishu_already_receiving", "飞书渠道已在接收消息")
        if self._runtime is not None:
            raise ChannelDeliveryError(
                "feishu_receiver_cleanup_required", "飞书接收运行时需要先完成清理"
            )
        if not self._account_options.get("receive_events", True):
            return
        sdk = await self._load_sdk()
        factory = self._websocket_factory or sdk.ws.Client
        secret = await self._resolve_secret()
        dispatcher = self._build_dispatcher(sdk)
        runtime = await _acquire_runtime(factory)
        loop = asyncio.get_running_loop()
        if loop is runtime.loop:
            await _release_runtime_async(runtime)
            raise ChannelDeliveryError(
                "feishu_event_loop_conflict", "飞书接收 loop 不能与应用 loop 共用"
            )
        self._handler = handler
        self._loop = loop
        self._runtime = runtime
        self._receiving = True
        self._websocket = None
        try:
            self._websocket = await runtime.call(
                _start_sdk_receiver(
                    factory,
                    self._account_options["app_id"],
                    secret,
                    dispatcher,
                    self._receiver_done,
                    self._remember_websocket,
                )
            )
        except BaseException as start_error:
            self._receiving = False
            self._handler = None
            self._loop = None
            try:
                await _release_runtime_async(runtime)
            except asyncio.CancelledError:
                self._websocket = None
                self._runtime = None
                raise
            except Exception as cleanup_error:
                raise ChannelDeliveryError(
                    "feishu_receiver_cleanup_failed",
                    "飞书接收启动失败后的运行时清理失败",
                    details={
                        "start_exception_type": type(start_error).__name__,
                        "cleanup_exception_type": type(cleanup_error).__name__,
                    },
                ) from None
            self._websocket = None
            self._runtime = None
            if isinstance(start_error, asyncio.CancelledError):
                raise
            if isinstance(start_error, ChannelDeliveryError):
                raise
            raise ChannelDeliveryError(
                "feishu_receiver_start_failed",
                "飞书 WebSocket 启动失败",
                details={"exception_type": type(start_error).__name__},
            ) from None

    async def _resolve_secret(self) -> str:
        if self._credentials is None:
            raise ChannelDeliveryError("credential_resolver_missing", "飞书凭据解析器未配置")
        ref = _CREDENTIAL_ADAPTER.validate_python(self._account_options["app_secret"])
        value = await self._credentials.resolve(ref)
        if not isinstance(value, str) or not value:
            raise ChannelDeliveryError("credential_invalid", "飞书 App Secret 凭据不可用")
        return value

    def _build_dispatcher(self, sdk: Any) -> Any:
        def on_message(data: Any) -> None:
            loop = self._loop
            if loop is None:
                return
            future = asyncio.run_coroutine_threadsafe(self._handle_event(data), loop)
            try:
                future.result(timeout=_EVENT_ADMISSION_TIMEOUT)
            except FutureTimeoutError as exc:
                future.cancel()
                raise ChannelDeliveryError(
                    "feishu_event_admission_timeout",
                    "飞书事件未能在时限内被 Manager 受理",
                    details={"timeout_seconds": _EVENT_ADMISSION_TIMEOUT},
                ) from exc
            except Exception as exc:
                raise ChannelDeliveryError(
                    "feishu_event_admission_failed",
                    "飞书事件未被 Manager 受理",
                    details={"exception_type": type(exc).__name__},
                ) from None

        try:
            builder = sdk.EventDispatcherHandler.builder("", "")
            return builder.register_p2_im_message_receive_v1(on_message).build()
        except Exception as exc:
            raise ChannelDeliveryError(
                "feishu_sdk_incompatible",
                "当前 lark-oapi 版本不支持 WebSocket 事件分发",
                details={"exception_type": type(exc).__name__},
            ) from exc

    def _remember_websocket(self, websocket: Any) -> None:
        self._websocket = websocket

    async def _handle_event(self, data: Any) -> None:
        event = _attr(data, "event", default=data)
        message = _attr(event, "message", default=event)
        sender = _attr(event, "sender", default=None)
        sender_type = _attr(sender, "sender_type", "type", default="user")
        if sender_type == "bot":
            # Do not feed the bot's own messages back into the Agent.
            return
        sender_id = _attr(
            _attr(sender, "sender_id", default=sender), "open_id", "user_id", "union_id"
        )
        message_id = _attr(message, "message_id", "message_id_v2")
        chat_id = _attr(message, "chat_id")
        msg_type = _attr(message, "message_type", "msg_type", default="text")
        content = _attr(message, "content", default="")
        if msg_type != "text" or not message_id or not chat_id or not sender_id:
            return
        try:
            parsed = json.loads(content) if isinstance(content, str) else content
        except (TypeError, ValueError):
            raise ChannelDeliveryError(
                "feishu_event_content_invalid", "飞书文本事件内容不是有效 JSON"
            ) from None
        if not isinstance(parsed, dict):
            raise ChannelDeliveryError("feishu_event_content_invalid", "飞书文本事件内容格式无效")
        text = parsed.get("text")
        if not isinstance(text, str):
            raise ChannelDeliveryError("feishu_event_content_invalid", "飞书文本事件缺少文本字段")
        if not text.strip() or self._handler is None:
            return
        inbound = InboundMessage(
            request_id=str(message_id),
            text=text,
            address=ChannelAddress(
                kind="chat_id",
                target=str(chat_id),
                sender=str(sender_id),
                message_id=str(message_id),
            ),
        )
        await self._handler(inbound)

    def _receiver_done(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None and self._receiving:
            _LOGGER.error(
                "feishu_receiver_stopped",
                extra={"exception_type": type(error).__name__},
            )

    async def stop_receiving(self) -> None:
        self._receiving = False
        websocket = self._websocket
        runtime = self._runtime
        self._handler = None
        self._loop = None
        if runtime is None:
            self._websocket = None
            return
        stop_error = None
        if websocket is not None and runtime.loop.is_running():
            try:
                await runtime.call(_stop_sdk_receiver(websocket))
            except Exception as exc:
                stop_error = exc
        try:
            await _release_runtime_async(runtime)
        except asyncio.CancelledError:
            self._websocket = None
            self._runtime = None
            raise
        except Exception as release_error:
            raise ChannelDeliveryError(
                "feishu_receiver_stop_failed",
                "飞书 WebSocket 运行时清理失败",
                details={
                    "stop_exception_type": type(stop_error).__name__ if stop_error else None,
                    "cleanup_exception_type": type(release_error).__name__,
                },
            ) from None
        self._websocket = None
        self._runtime = None
        if stop_error is not None:
            raise ChannelDeliveryError(
                "feishu_receiver_stop_failed",
                "飞书 WebSocket 清理失败",
                details={"exception_type": type(stop_error).__name__},
            ) from None


class FeishuChannelType:
    name = "feishu"
    id_prefix = "feishu"
    description = "飞书官方 Bot 双向消息与通知渠道"
    capabilities = ["notification", "conversation"]
    options_schema = _OPTIONS_SCHEMA

    async def create(self, config: ChannelConfig, credentials: Any) -> FeishuChannel:
        return FeishuChannel(config, credentials)
