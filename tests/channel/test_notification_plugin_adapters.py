from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflowweave.channel.conversation import ChannelAddress, InboundMessage
from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.models import ChannelConfig, Notification

_CHANNEL_PLUGIN_ROOT = Path(__file__).parents[2] / "src" / "workflowweave" / "plugins" / "channel"


def _load_channel(module_name: str, plugin: str):
    path = _CHANNEL_PLUGIN_ROOT / plugin / "channel.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _Credentials:
    async def resolve(self, credential):
        return "secret-value"


def _qq_config(*, target_kind=None, target_id=None):
    options = {
        "app_id": "app-1",
        "client_secret": {"kind": "env", "name": "QQ_SECRET"},
    }
    if target_kind is not None:
        options.update(target_kind=target_kind, target_id=target_id)
    return ChannelConfig(id="qq-one", channel="qq", options=options)


class _QQApi:
    def __init__(self):
        self.calls = []

    async def post_c2c_message(self, **kwargs):
        self.calls.append(("c2c", kwargs))
        return {"id": "sent-c2c"}

    async def post_group_message(self, **kwargs):
        self.calls.append(("group", kwargs))
        return {"id": "sent-group"}

    async def post_message(self, **kwargs):
        self.calls.append(("guild", kwargs))
        return {"id": "sent-guild"}

    async def post_dms(self, **kwargs):
        self.calls.append(("dm", kwargs))
        return {"id": "sent-dm"}


class _QQTestHttp:
    def __init__(self, *, timeout, is_sandbox=False):
        self.timeout = timeout
        self.is_sandbox = is_sandbox
        self.api = _QQApi()

    async def close(self):
        return None


class _QQTestBotAPI:
    def __init__(self, *, http):
        self._api = http.api
        self.calls = self._api.calls

    def __getattr__(self, name):
        return getattr(self._api, name)


class _QQClient:
    instances = []

    def __init__(self, *, intents, log_level=None):
        self.intents = intents
        self.log_level = log_level
        self.http = _QQTestHttp(timeout=5)
        self.api = _QQTestBotAPI(http=self.http)
        self.closed = False
        self.started = []
        self.gateway_calls = 0
        self.instances.append(self)

    async def start(self, *, appid, secret, ret_coro):
        self.started.append((appid, secret, ret_coro))
        return self._gateway()

    async def _gateway(self):
        self.gateway_calls += 1
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_botpy(monkeypatch):
    module = SimpleNamespace(
        Client=_QQClient,
        Intents=lambda **kwargs: kwargs,
        http=SimpleNamespace(BotHttp=_QQTestHttp),
        api=SimpleNamespace(BotAPI=_QQTestBotAPI),
    )
    monkeypatch.setitem(sys.modules, "botpy", module)
    monkeypatch.setitem(sys.modules, "botpy.http", module.http)
    monkeypatch.setitem(sys.modules, "botpy.gateway", SimpleNamespace(BotWebSocket=object))
    _QQClient.instances.clear()
    return module


@pytest.mark.asyncio
async def test_qq_sdk_login_send_reply_and_inbound_route(fake_botpy):
    del fake_botpy
    QQChannel = _load_channel("qq_notification_plugin_test", "qq").QQChannel

    channel = QQChannel(
        _qq_config(target_kind="c2c", target_id="user-1"),
        _Credentials(),
    )
    inbound = []
    await channel.start()
    client = _QQClient.instances[-1]
    assert client.log_level == logging.INFO
    assert client.started == [("app-1", "secret-value", True)]

    async def receive(message):
        inbound.append(message)
        return {"status": "accepted"}

    await channel.start_receiving(receive)
    await asyncio.sleep(0)
    assert client.gateway_calls == 1
    await client.on_c2c_message_create(SimpleNamespace(
        id="message-1",
        content="hello Agent",
        author=SimpleNamespace(user_openid="user-1"),
    ))
    assert inbound == [InboundMessage(
        request_id="message-1",
        text="hello Agent",
        address=ChannelAddress(
            kind="c2c", target="user-1", sender="user-1", message_id="message-1",
            conversation_type="private",
        ),
    )]

    await channel.reply(
        Notification(session_id="session-1", output_id="output-1", text="hello back"),
        address=inbound[0].address,
        options={},
    )
    await channel.send(
        Notification(session_id="session-1", output_id="output-2", text="notice"),
        options={"target_kind": "group", "target_id": "group-9"},
    )
    assert client.api.calls == [
        ("c2c", {"content": "hello back", "openid": "user-1", "msg_id": "message-1"}),
        ("group", {"content": "notice", "group_openid": "group-9"}),
    ]
    assert client.gateway_calls == 1

    await channel.stop_receiving()
    assert client.closed
    await channel.send(
        Notification(session_id="session-1", output_id="output-3", text="after stop"),
        options={"target_kind": "c2c", "target_id": "user-after-stop"},
    )
    restarted_client = _QQClient.instances[-1]
    assert restarted_client is not client
    assert restarted_client.started == [("app-1", "secret-value", True)]
    assert restarted_client.api.calls == [("c2c", {
        "content": "after stop", "openid": "user-after-stop",
    })]
    assert restarted_client.gateway_calls == 0

    await channel.start_receiving(receive)
    assert len(_QQClient.instances) == 2
    await asyncio.sleep(0)
    assert restarted_client.gateway_calls == 1
    await channel.stop()


@pytest.mark.asyncio
async def test_qq_sdk_import_does_not_block_event_loop(fake_botpy, monkeypatch):
    QQChannel = _load_channel("qq_import_thread_plugin_test", "qq").QQChannel
    module = sys.modules["qq_import_thread_plugin_test"]
    real_import = module.importlib.import_module
    entered = threading.Event()
    release = threading.Event()

    def import_module(name):
        if name == "botpy":
            entered.set()
            if not release.wait(timeout=2):
                raise TimeoutError("import was not released")
            return sys.modules["botpy"]
        return real_import(name)

    async def initialize(_self):
        return None

    monkeypatch.setattr(module.importlib, "import_module", import_module)
    monkeypatch.setattr(QQChannel, "_initialize_client", initialize)
    channel = QQChannel(_qq_config(), _Credentials())
    starting = asyncio.create_task(channel.start())
    assert await asyncio.to_thread(entered.wait, 1)
    await asyncio.wait_for(asyncio.sleep(0.02), timeout=0.2)
    assert not starting.done()
    release.set()
    await starting
    await channel.stop()


@pytest.mark.asyncio
async def test_qq_dm_uses_official_post_dms_route(fake_botpy):
    del fake_botpy
    QQChannel = _load_channel("qq_dm_notification_plugin_test", "qq").QQChannel

    channel = QQChannel(_qq_config(), _Credentials())
    await channel.start()
    client = _QQClient.instances[-1]
    await channel.reply(
        Notification(session_id="session-1", output_id="output-1", text="reply"),
        address=ChannelAddress(
            kind="dm", target="guild-1", sender="user-1", message_id="message-1"
        ),
        options={},
    )
    assert client.api.calls == [("dm", {
        "content": "reply", "guild_id": "guild-1", "msg_id": "message-1",
    })]
    await channel.stop()


@pytest.mark.asyncio
async def test_qq_send_workflow_target_does_not_start_gateway(fake_botpy):
    del fake_botpy
    QQChannel = _load_channel("qq_send_plugin_test", "qq").QQChannel
    channel = QQChannel(_qq_config(), _Credentials())
    await channel.start()
    client = _QQClient.instances[-1]

    await channel.send(
        Notification(session_id="session-1", output_id="output-1", text="notice"),
        options={"target_kind": "c2c", "target_id": "override-user"},
    )

    assert client.api.calls == [("c2c", {
        "content": "notice", "openid": "override-user",
    })]
    assert channel._runner is None
    assert client.gateway_calls == 0
    await channel.stop()
    assert channel._gateway_coro is None


@pytest.mark.asyncio
async def test_qq_receiver_start_rejection_is_observable(fake_botpy):
    del fake_botpy
    QQChannel = _load_channel("qq_receiver_failure_plugin_test", "qq").QQChannel
    channel = QQChannel(_qq_config(), _Credentials())
    await channel.start()
    gateway = channel._gateway_coro
    channel._gateway_coro = None
    gateway.close()

    with pytest.raises(ChannelDeliveryError) as error:
        await channel.start_receiving(lambda _message: asyncio.sleep(0))

    assert error.value.code == "qq_sdk_invalid"
    assert channel.receiver_status() == {"state": "failed", "error": "qq_sdk_invalid"}
    await channel.stop()


class _TelegramBot:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.response = SimpleNamespace(message_id=42)

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return self.response


class _Updater:
    def __init__(self):
        self.running = False
        self.start_calls = 0
        self.stop_calls = 0

    async def start_polling(self, *, error_callback=None):
        if self.running:
            raise RuntimeError("already running")
        self.running = True
        self.error_callback = error_callback
        self.start_calls += 1
        return None

    async def stop(self):
        if not self.running:
            raise RuntimeError("This Updater is not running!")
        self.running = False
        self.stop_calls += 1
        return None


class _TelegramApplication:
    def __init__(self):
        self.bot = _TelegramBot()
        self.updater = _Updater()
        self.events = []
        self.handlers = []
        self.running = False

    def add_handler(self, handler):
        self.handlers.append(handler)

    async def initialize(self):
        self.events.append("initialize")

    async def start(self):
        if self.running:
            raise RuntimeError("already running")
        self.running = True
        self.events.append("start")

    async def stop(self):
        if not self.running:
            raise RuntimeError("not running")
        self.running = False
        self.events.append("stop")

    async def shutdown(self):
        self.events.append("shutdown")


@pytest.mark.asyncio
async def test_telegram_single_direction_send_and_reply_use_sdk_application():
    TelegramChannel = _load_channel(
        "telegram_notification_plugin_test", "telegram"
    ).TelegramChannel

    application = _TelegramApplication()
    channel = TelegramChannel(
        ChannelConfig(
            id="telegram-one",
            channel="telegram",
            options={
                "token": {"kind": "env", "name": "TELEGRAM_TOKEN"},
                "chat_id": "chat-1",
            },
        ),
        _Credentials(),
        application_factory=lambda token: application,
    )
    await channel.start()
    await channel.send(
        Notification(session_id="session-1", output_id="output-1", text="notice"),
        options={},
    )
    await channel.reply(
        Notification(session_id="session-1", output_id="output-2", text="reply"),
        address=ChannelAddress(
            kind="telegram", target="chat-2", sender="user-2", message_id="7"
        ),
        options={},
    )
    assert application.events == ["initialize"]
    assert application.bot.calls == [
        {"chat_id": "chat-1", "text": "notice"},
        {"chat_id": "chat-2", "text": "reply", "reply_to_message_id": 7},
    ]
    await channel.stop()
    assert application.events == ["initialize", "shutdown"]
    assert application.updater.stop_calls == 0


@pytest.mark.asyncio
async def test_telegram_application_uses_channel_timeout_for_both_request_pools(monkeypatch):
    telegram_ext = pytest.importorskip("telegram.ext")
    TelegramChannel = _load_channel(
        "telegram_timeout_plugin_test", "telegram"
    ).TelegramChannel
    application = _TelegramApplication()
    calls = []

    class Builder:
        def token(self, value):
            calls.append(("token", value))
            return self

        def build(self):
            return application

    builder = Builder()
    timeout_methods = (
        "connect_timeout",
        "read_timeout",
        "write_timeout",
        "pool_timeout",
        "get_updates_connect_timeout",
        "get_updates_read_timeout",
        "get_updates_write_timeout",
        "get_updates_pool_timeout",
    )
    for method_name in timeout_methods:
        setattr(
            builder,
            method_name,
            lambda value, method_name=method_name: calls.append((method_name, value)) or builder,
        )
    monkeypatch.setattr(
        telegram_ext.Application,
        "builder",
        classmethod(lambda cls: builder),
    )
    channel = TelegramChannel(
        ChannelConfig(
            id="telegram-timeouts",
            channel="telegram",
            timeout=17.0,
            options={"token": {"kind": "env", "name": "TELEGRAM_TOKEN"}},
        ),
        _Credentials(),
    )

    await channel.start()

    assert calls == [
        ("token", "secret-value"),
        *[(name, 17.0) for name in timeout_methods],
    ]
    await channel.stop()


@pytest.mark.asyncio
async def test_telegram_http_client_construction_does_not_block_event_loop(monkeypatch):
    telegram_ext = pytest.importorskip("telegram.ext")
    TelegramChannel = _load_channel(
        "telegram_request_build_thread_test", "telegram"
    ).TelegramChannel
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    class Request:
        def __init__(self, get_updates):
            self.get_updates = get_updates
            self.closed = False

        async def shutdown(self):
            self.closed = True

    class Builder:
        def token(self, value):
            del value
            return self

        def connect_timeout(self, value):
            del value
            return self

        def read_timeout(self, value):
            del value
            return self

        def write_timeout(self, value):
            del value
            return self

        def pool_timeout(self, value):
            del value
            return self

        def get_updates_connect_timeout(self, value):
            del value
            return self

        def get_updates_read_timeout(self, value):
            del value
            return self

        def get_updates_write_timeout(self, value):
            del value
            return self

        def get_updates_pool_timeout(self, value):
            del value
            return self

        def _build_request(self, get_updates):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(timeout=2):
                raise TimeoutError("request build was not released")
            return Request(get_updates)

        def request(self, request):
            self.request_instance = request
            return self

        def get_updates_request(self, request):
            self.get_updates_request_instance = request
            return self

        def build(self):
            return _TelegramApplication()

    monkeypatch.setattr(telegram_ext.Application, "builder", classmethod(lambda cls: Builder()))
    channel = TelegramChannel(
        ChannelConfig(
            id="telegram-threaded-build",
            channel="telegram",
            timeout=17.0,
            options={"token": {"kind": "env", "name": "TELEGRAM_TOKEN"}},
        ),
        _Credentials(),
    )
    starting = asyncio.create_task(channel.start())
    await asyncio.wait_for(entered.wait(), timeout=1)
    await asyncio.wait_for(asyncio.sleep(0.02), timeout=0.2)
    assert not starting.done()
    release.set()
    await starting
    await channel.stop()


@pytest.mark.asyncio
async def test_telegram_cancelled_request_build_closes_worker_clients():
    TelegramChannel = _load_channel(
        "telegram_request_build_cancel_test", "telegram"
    ).TelegramChannel
    entered = threading.Event()
    release = threading.Event()
    built = []

    class Request:
        def __init__(self):
            self.closed = False

        async def shutdown(self):
            self.closed = True

    def build_request(_get_updates):
        entered.set()
        if not release.wait(timeout=2):
            raise TimeoutError("request build was not released")
        request = Request()
        built.append(request)
        return request

    channel = TelegramChannel.__new__(TelegramChannel)
    task = asyncio.create_task(channel._build_requests_off_loop(object(), build_request))
    await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert built and all(request.closed for request in built)


def _telegram_update(*, chat_id, user_id, message_id, text="hello Agent"):
    from datetime import UTC, datetime

    from telegram import Chat, Message, MessageEntity, Update, User

    entities = []
    if text.startswith("/"):
        command = text.split(maxsplit=1)[0]
        entities.append(MessageEntity(MessageEntity.BOT_COMMAND, 0, len(command)))
    message = Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(chat_id, "supergroup" if chat_id < 0 else "private"),
        from_user=User(user_id, "Test", is_bot=False) if user_id is not None else None,
        text=text,
        entities=entities,
    )
    return Update(update_id=message_id, message=message)


@pytest.mark.asyncio
async def test_telegram_inbound_deduplicates_by_chat_and_requires_real_user():
    TelegramChannel = _load_channel(
        "telegram_inbound_plugin_test", "telegram"
    ).TelegramChannel
    application = _TelegramApplication()
    channel = TelegramChannel(
        ChannelConfig(
            id="telegram-duplex",
            channel="telegram",
            options={"token": {"kind": "env", "name": "TELEGRAM_TOKEN"}},
        ),
        _Credentials(),
        application_factory=lambda token: application,
    )
    received = []

    async def enqueue(message):
        received.append(message)
        return {"status": "accepted"}

    await channel.start()
    await channel.start_receiving(enqueue)
    assert application.events == ["initialize", "start"]
    assert len(application.handlers) == 1
    assert channel.receiver_status() == {"state": "running", "error": None}
    assert callable(application.updater.error_callback)

    message_handler = application.handlers[0]
    updates = [
        _telegram_update(chat_id=-1001, user_id=51, message_id=7, text="/new"),
        _telegram_update(chat_id=-1002, user_id=51, message_id=7),
        _telegram_update(chat_id=-1003, user_id=None, message_id=7),
    ]
    for update in updates:
        assert message_handler.check_update(update) is not None
        await message_handler.callback(update, None)
    assert [item.request_id for item in received] == ["-1001:7", "-1002:7"]
    assert [item.address.sender for item in received] == ["51", "51"]
    assert [item.text for item in received] == ["/new", "hello Agent"]

    await channel.stop_receiving()
    assert application.updater.stop_calls == 1
    assert application.events == ["initialize", "start"]
    assert channel.receiver_status() == {"state": "stopped", "error": None}
    application.updater.error_callback(RuntimeError("polling rejected"))
    assert channel.receiver_status() == {"state": "failed", "error": "RuntimeError"}
    await channel.start_receiving(enqueue)
    assert application.events == ["initialize", "start"]
    assert application.updater.start_calls == 2
    assert len(application.handlers) == 1
    await channel.stop_receiving()
    await channel.stop()
    assert application.events == ["initialize", "start", "stop", "shutdown"]
    assert application.updater.stop_calls == 2


@pytest.mark.asyncio
async def test_telegram_api_rejection_rate_limit_and_network_uncertainty():
    telegram_error = pytest.importorskip("telegram.error")
    TelegramChannel = _load_channel(
        "telegram_send_errors_plugin_test", "telegram"
    ).TelegramChannel
    application = _TelegramApplication()
    channel = TelegramChannel(
        ChannelConfig(
            id="telegram-errors",
            channel="telegram",
            options={"token": {"kind": "env", "name": "TELEGRAM_TOKEN"}, "chat_id": 1},
        ),
        _Credentials(),
        application_factory=lambda token: application,
    )
    await channel.start()
    notification = Notification(session_id="session-1", output_id="output-1", text="notice")

    for failure, code, uncertain in (
        (telegram_error.BadRequest("chat not found"), "telegram_rejected", False),
        (telegram_error.RetryAfter(timedelta(seconds=3)), "telegram_rate_limited", False),
        (telegram_error.NetworkError("connection lost"), "telegram_send_uncertain", True),
    ):
        application.bot.failure = failure
        with pytest.raises(ChannelDeliveryError) as error:
            await channel.send(notification, options={})
        assert error.value.code == code
        assert error.value.uncertain is uncertain

    application.bot.failure = None
    application.bot.response = None
    with pytest.raises(ChannelDeliveryError) as error:
        await channel.send(notification, options={})
    assert error.value.code == "telegram_send_uncertain"
    assert error.value.uncertain is True
    await channel.stop()
