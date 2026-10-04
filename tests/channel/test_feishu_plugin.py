from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from logagent.channel.conversation import ChannelAddress, InboundMessage
from logagent.models import ChannelConfig, Notification

_PLUGIN_ROOT = Path(__file__).parents[2] / "plugins" / "channel" / "feishu"


def _load_channel():
    name = "feishu_notification_plugin_test"
    spec = importlib.util.spec_from_file_location(name, _PLUGIN_ROOT / "channel.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.FeishuChannel, module


class _Credentials:
    async def resolve(self, credential):
        assert credential.kind == "env"
        assert credential.name == "FEISHU_APP_SECRET"
        return "secret-value"


class _Builder:
    def __init__(self):
        self.values = {}

    def __getattr__(self, name):
        def set_value(value):
            self.values[name] = value
            return self

        return set_value

    def build(self):
        return SimpleNamespace(**self.values)


class _Model:
    @staticmethod
    def builder():
        return _Builder()


class _MessageResource:
    def __init__(self):
        self.calls = []

    async def acreate(self, request):
        self.calls.append(("create", request))
        return SimpleNamespace(code=0)

    async def areply(self, request):
        self.calls.append(("reply", request))
        return SimpleNamespace(code=0)


class _Client:
    def __init__(self):
        self.message = _MessageResource()
        self.im = SimpleNamespace(v1=SimpleNamespace(message=self.message))


class _ClientBuilder:
    def __init__(self):
        self.values = {}

    def app_id(self, value):
        self.values["app_id"] = value
        return self

    def app_secret(self, value):
        self.values["app_secret"] = value
        return self

    def build(self):
        return _Client()


class _SDKClient:
    @staticmethod
    def builder():
        return _ClientBuilder()


class _EventHandlerBuilder:
    def __init__(self):
        self.callback = None

    def register_p2_im_message_receive_v1(self, callback):
        self.callback = callback
        return self

    def build(self):
        return self


class _EventDispatcherHandler:
    @staticmethod
    def builder(_app_id, _app_secret):
        return _EventHandlerBuilder()


class _WebSocket:
    instances = []

    def __init__(self, _app_id, _secret, *, event_handler):
        self.event_handler = event_handler
        self._conn = None
        self._auto_reconnect = True
        self._disconnected = asyncio.Event()
        self._reconnect_requested = asyncio.Event()
        self._connected_twice = asyncio.Event()
        self.connects = 0
        self.instances.append(self)

    async def _connect(self):
        self.connects += 1
        if self.connects >= 2:
            self._connected_twice.set()
        self._conn = object()
        asyncio.create_task(self._receive_message_loop())

    async def _receive_message_loop(self):
        await self._reconnect_requested.wait()
        if self._auto_reconnect:
            self._reconnect_requested.clear()
            await self._connect()

    async def _ping_loop(self):
        await asyncio.Event().wait()

    async def _disconnect(self):
        self._conn = None
        self._disconnected.set()

    async def request_reconnect(self):
        self._reconnect_requested.set()
        await self._connected_twice.wait()

    async def emit(self, event):
        return self.event_handler.callback(event)


_MODELS = SimpleNamespace(
    CreateMessageRequest=_Model,
    CreateMessageRequestBody=_Model,
    ReplyMessageRequest=_Model,
    ReplyMessageRequestBody=_Model,
)
_SDK = SimpleNamespace(
    Client=_SDKClient,
    EventDispatcherHandler=_EventDispatcherHandler,
    ws=SimpleNamespace(Client=_WebSocket),
    api=SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(model=_MODELS))),
)


def _config():
    return ChannelConfig(
        id="feishu-one",
        channel="feishu",
        timeout=1,
        options={
            "app_id": "app-one",
            "app_secret": {"kind": "env", "name": "FEISHU_APP_SECRET"},
            "target_kind": "chat_id",
            "target_id": "chat-one",
        },
    )


@pytest.mark.asyncio
async def test_send_and_reply_use_official_async_routes_and_original_message_id():
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), sdk=_SDK)
    await channel.start()

    await channel.send(
        Notification(session_id="session-one", output_id="notice", text="notice"),
        options={},
    )
    await channel.reply(
        Notification(session_id="session-one", output_id="reply", text="reply"),
        address=ChannelAddress(
            kind="chat_id", target="chat-one", sender="open-one", message_id="original-one"
        ),
        options={},
    )

    assert [kind for kind, _request in channel._client.message.calls] == ["create", "reply"]
    create = channel._client.message.calls[0][1]
    assert create.receive_id_type == "chat_id"
    assert create.request_body.receive_id == "chat-one"
    assert json.loads(create.request_body.content) == {"text": "notice"}
    reply = channel._client.message.calls[1][1]
    assert reply.message_id == "original-one"
    assert reply.request_body.msg_type == "text"
    assert json.loads(reply.request_body.content) == {"text": "reply"}
    await channel.stop()


@pytest.mark.asyncio
async def test_response_without_success_receipt_is_not_accepted():
    FeishuChannel, plugin_module = _load_channel()
    assert not plugin_module._response_ok(SimpleNamespace())


@pytest.mark.asyncio
async def test_websocket_callback_waits_for_manager_admission_and_stop_cleans_tasks():
    FeishuChannel, _ = _load_channel()
    _WebSocket.instances.clear()
    channel = FeishuChannel(_config(), _Credentials(), sdk=_SDK)
    await channel.start()
    received = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def manager_admission(message):
        received.append(message)
        entered.set()
        await release.wait()
        return {"status": "accepted"}

    try:
        await channel.start_receiving(manager_admission)
        websocket = _WebSocket.instances[-1]
        runtime = channel._runtime
        assert runtime is not None
        assert runtime.loop is not asyncio.get_running_loop()
        event = SimpleNamespace(
            event=SimpleNamespace(
                message=SimpleNamespace(
                    message_id="message-one",
                    chat_id="chat-one",
                    message_type="text",
                    content=json.dumps({"text": "hello"}),
                ),
                sender=SimpleNamespace(
                    sender_type="user",
                    sender_id=SimpleNamespace(open_id="open-one"),
                ),
            )
        )
        callback = asyncio.create_task(runtime.call(websocket.emit(event)))
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert not callback.done()
        assert received == [
            InboundMessage(
                request_id="message-one",
                text="hello",
                address=ChannelAddress(
                    kind="chat_id", target="chat-one", sender="open-one", message_id="message-one"
                ),
            )
        ]

        release.set()
        await asyncio.wait_for(callback, timeout=1)
        await asyncio.wait_for(runtime.call(websocket.request_reconnect()), timeout=1)
        assert websocket.connects == 2
        await channel.stop_receiving()
        assert websocket._conn is None
        assert websocket._auto_reconnect is False

        assert runtime.loop.is_closed()
        assert not runtime._thread.is_alive()
    finally:
        release.set()
        await channel.stop()


@pytest.mark.asyncio
async def test_instances_share_sdk_loop_until_last_receiver_stops():
    FeishuChannel, _ = _load_channel()
    _WebSocket.instances.clear()
    first = FeishuChannel(_config(), _Credentials(), sdk=_SDK)
    second = FeishuChannel(_config(), _Credentials(), sdk=_SDK)
    await first.start()
    await second.start()

    async def accepted(_message):
        return {"status": "accepted"}

    await first.start_receiving(accepted)
    await second.start_receiving(accepted)
    runtime = first._runtime
    assert runtime is not None and second._runtime is runtime
    assert runtime.references == 2

    await first.stop_receiving()
    assert runtime.references == 1
    assert runtime.loop.is_running()

    await second.stop_receiving()
    assert runtime.references == 0
    assert runtime.loop.is_closed()
    assert not runtime._thread.is_alive()
    await first.stop()
    await second.stop()


@pytest.mark.asyncio
async def test_cancelled_runtime_acquire_releases_reference_after_worker_finishes(monkeypatch):
    _, plugin_module = _load_channel()
    module = ModuleType("feishu_acquire_cancel_test")
    factory = SimpleNamespace(__module__="feishu_acquire_cancel_test")
    started = threading.Event()
    continue_acquire = threading.Event()
    acquired = []
    original_acquire = plugin_module._acquire_runtime_for_module

    def import_module(_name):
        return module

    def delayed_acquire(sdk_module):
        started.set()
        if not continue_acquire.wait(timeout=2):
            raise TimeoutError("test acquire was not released")
        runtime = original_acquire(sdk_module)
        acquired.append(runtime)
        return runtime

    monkeypatch.setattr(plugin_module.importlib, "import_module", import_module)
    monkeypatch.setattr(plugin_module, "_acquire_runtime_for_module", delayed_acquire)
    acquisition = asyncio.create_task(plugin_module._acquire_runtime(factory))
    await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=1)
    acquisition.cancel()
    continue_acquire.set()

    with pytest.raises(asyncio.CancelledError):
        await acquisition

    assert len(acquired) == 1
    assert acquired[0].references == 0
    assert acquired[0].loop.is_closed()
    assert module not in plugin_module._SDK_RUNTIMES


@pytest.mark.asyncio
async def test_runtime_stop_failure_can_be_retried_without_releasing_twice():
    FeishuChannel, _ = _load_channel()
    _WebSocket.instances.clear()
    channel = FeishuChannel(_config(), _Credentials(), sdk=_SDK)
    await channel.start()
    await channel.start_receiving(lambda _message: asyncio.sleep(0))
    runtime = channel._runtime
    assert runtime is not None
    original_stop = runtime.stop_and_join
    attempts = 0

    def fail_first_stop():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected runtime shutdown failure")
        original_stop()

    runtime.stop_and_join = fail_first_stop
    with pytest.raises(Exception, match="运行时清理失败"):
        await channel.stop()

    assert runtime.references == 0
    assert runtime.stopping
    assert channel._runtime is runtime

    await channel.stop()
    assert attempts == 2
    assert runtime.loop.is_closed()
    assert not runtime._thread.is_alive()
    assert channel._runtime is None
    await channel.stop()


@pytest.mark.asyncio
async def test_failed_receiver_start_keeps_client_and_runtime_for_stop_retry(monkeypatch):
    FeishuChannel, plugin_module = _load_channel()
    _WebSocket.instances.clear()
    channel = FeishuChannel(_config(), _Credentials(), sdk=_SDK)
    await channel.start()

    async def fail_with_receiver_task(
        factory, app_id, secret, dispatcher, _receiver_done, receiver_created
    ):
        websocket = factory(app_id, secret, event_handler=dispatcher)
        receiver_created(websocket)
        asyncio.create_task(websocket._receive_message_loop())
        raise RuntimeError("injected receiver startup failure")

    monkeypatch.setattr(plugin_module, "_start_sdk_receiver", fail_with_receiver_task)
    with pytest.raises(Exception, match="运行时清理失败"):
        await channel.start_receiving(lambda _message: asyncio.sleep(0))

    runtime = channel._runtime
    websocket = channel._websocket
    assert runtime is not None and runtime.references == 0 and runtime.stopping
    assert websocket is _WebSocket.instances[-1]

    await channel.stop()
    assert runtime.loop.is_closed()
    assert not runtime._thread.is_alive()
    assert channel._runtime is None
    assert websocket._auto_reconnect is False


@pytest.mark.asyncio
async def test_stop_receiving_releases_runtime_without_websocket():
    FeishuChannel, plugin_module = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), sdk=_SDK)
    runtime = await plugin_module._acquire_runtime(_WebSocket)
    channel._runtime = runtime

    await channel.stop_receiving()

    assert runtime.references == 0
    assert runtime.loop.is_closed()
    assert not runtime._thread.is_alive()
    assert channel._runtime is None
    await channel.stop()


@pytest.mark.asyncio
async def test_real_lark_websocket_client_private_lifecycle_contract(monkeypatch):
    try:
        sdk = await asyncio.to_thread(importlib.import_module, "lark_oapi")
        sdk_ws = await asyncio.to_thread(importlib.import_module, "lark_oapi.ws.client")
    except ImportError:
        pytest.skip("lark-oapi optional dependency is not installed")

    FeishuChannel, _ = _load_channel()
    sdk_client = sdk_ws.Client
    endpoint = "wss://example.invalid/callback?device_id=device-one&service_id=42"

    class Connection:
        def __init__(self):
            self.closed = asyncio.Event()

        async def recv(self):
            await self.closed.wait()
            raise RuntimeError("test connection closed")

        async def send(self, _frame):
            return None

        async def close(self):
            self.closed.set()

    connection = Connection()

    async def connect(_endpoint, **_kwargs):
        assert _endpoint == endpoint
        return connection

    monkeypatch.setattr(sdk_client, "_get_conn_url", lambda _client: endpoint)
    monkeypatch.setattr(sdk_ws.websockets, "connect", connect)
    channel = FeishuChannel(
        _config(),
        _Credentials(),
        sdk=sdk,
        client_factory=lambda **_kwargs: _Client(),
        websocket_factory=sdk_client,
    )
    await channel.start()
    await channel.start_receiving(lambda _message: asyncio.sleep(0))
    websocket = channel._websocket
    runtime = channel._runtime
    assert websocket is not None and runtime is not None
    assert websocket._conn is connection
    cache_task = websocket._cache._cron

    await channel.stop_receiving()
    assert connection.closed.is_set()
    assert websocket._conn is None
    assert cache_task.done()
    assert runtime.loop.is_closed()
    assert not runtime._thread.is_alive()
    await channel.stop()
