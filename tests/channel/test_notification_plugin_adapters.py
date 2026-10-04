from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from logagent.channel.conversation import ChannelAddress, InboundMessage
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


class _QQClient:
    instances = []

    def __init__(self, *, intents):
        self.intents = intents
        self.api = _QQApi()
        self.closed = False
        self.started = []
        self.instances.append(self)

    async def start(self, *, appid, secret, ret_coro):
        self.started.append((appid, secret, ret_coro))
        return self._gateway()

    async def _gateway(self):
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_botpy(monkeypatch):
    module = SimpleNamespace(Client=_QQClient, Intents=lambda **kwargs: kwargs)
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
    assert client.started == [("app-1", "secret-value", True)]

    async def receive(message):
        inbound.append(message)
        return {"status": "accepted"}

    await channel.start_receiving(receive)
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
        options={},
    )
    assert client.api.calls == [
        ("c2c", {"content": "hello back", "openid": "user-1", "msg_id": "message-1"}),
        ("c2c", {"content": "notice", "openid": "user-1"}),
    ]

    await channel.stop_receiving()
    assert client.closed
    # Manager suspend/resume closes the SDK transport and starts a fresh client.
    await channel.start_receiving(receive)
    assert len(_QQClient.instances) == 2
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


class _TelegramBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)


class _Updater:
    async def start_polling(self):
        return None

    async def stop(self):
        return None


class _TelegramApplication:
    def __init__(self):
        self.bot = _TelegramBot()
        self.updater = _Updater()
        self.events = []
        self.handlers = []

    def add_handler(self, handler):
        self.handlers.append(handler)

    async def initialize(self):
        self.events.append("initialize")

    async def start(self):
        self.events.append("start")

    async def stop(self):
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
