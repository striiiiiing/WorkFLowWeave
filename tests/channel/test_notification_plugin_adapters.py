from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from logagent.channel.conversation import ChannelAddress, InboundMessage
from logagent.channel.errors import ChannelDeliveryError
from logagent.models import ChannelConfig, Notification

_CHANNEL_PLUGIN_ROOT = Path(__file__).parents[2] / "plugins" / "channel"


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
            kind="c2c", target="user-1", sender="user-1", message_id="message-1"
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

    async def start_polling(self):
        if self.running:
            raise RuntimeError("already running")
        self.running = True
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
