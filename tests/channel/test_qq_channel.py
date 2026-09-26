from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import AIMessage

from logagent.agent.commands import AgentChannel
from logagent.agent.config import AgentConfig
from logagent.agent.service import AgentService
from logagent.channel.context import delivery_deadline
from logagent.channel.conversation import ChannelAddress, InboundMessage
from logagent.channel.errors import ChannelDeliveryError
from logagent.channel.manager import ChannelManager
from logagent.channel.qq import QQChannel, QQChannelType
from logagent.config import PluginRegistry
from logagent.errors import LogAgentError
from logagent.models import ChannelConfig, Notification, SystemConfig
from tests.agent.helpers import ScriptedModel


class _Credentials:
    async def resolve(self, credential):
        assert credential.kind == "env"
        assert credential.name == "QQ_SECRET"
        return "secret-value"


class _WebSocket:
    def __init__(self, frames=()):
        self.frames = asyncio.Queue()
        for frame in frames:
            self.frames.put_nowait(json.dumps(frame))
        self.sent = []
        self.sent_event = asyncio.Event()
        self.closed = False

    async def recv(self):
        frame = await self.frames.get()
        if frame is None:
            raise RuntimeError("websocket closed")
        return frame

    def push(self, frame):
        self.frames.put_nowait(json.dumps(frame))

    async def send(self, frame):
        self.sent.append(json.loads(frame))
        self.sent_event.set()

    async def close(self):
        self.closed = True
        self.frames.put_nowait(None)


def _config(*, target_kind="c2c", target_id="openid-1", agent_enabled=True):
    options = {
        "app_id": "app-1",
        "client_secret": {"kind": "env", "name": "QQ_SECRET"},
    }
    if target_kind is not None:
        options["target_kind"] = target_kind
        options["target_id"] = target_id
    return ChannelConfig(
        id="qq-account",
        channel="qq",
        options=options,
        timeout=1,
        agent_enabled=agent_enabled,
    )


def _http_transport(requests=None, *, send_status=200, send_handler=None):
    requests = requests if requests is not None else []

    async def handle(request):
        requests.append(request)
        if request.url.host == "bots.qq.com":
            return httpx.Response(200, json={"access_token": "token-1", "expires_in": 7200})
        if request.url.path == "/gateway":
            return httpx.Response(200, json={"url": "wss://gateway.example"})
        if send_handler is not None:
            return await send_handler(request)
        return httpx.Response(send_status, json={"id": "sent-message"})

    return httpx.MockTransport(handle), requests


def _notification(text="hello"):
    return Notification(session_id="session-1", output_id="output-1", text=text)


@pytest.mark.asyncio
async def test_type_uses_official_qq_capabilities_and_secret_reference():
    channel_type = QQChannelType()
    assert channel_type.name == "qq"
    assert channel_type.capabilities == ["notification", "conversation"]

    transport, _ = _http_transport()
    instance = await channel_type.create(_config(), _Credentials())
    instance._http_transport = transport
    await instance.start()
    await instance.stop()


@pytest.mark.asyncio
async def test_resident_started_for_notifications_can_later_start_receiving():
    socket = _WebSocket([{"op": 10, "d": {"heartbeat_interval": 60_000}}])
    transport, _ = _http_transport()

    async def connect(_url):
        return socket

    channel = QQChannel(
        _config(agent_enabled=False),
        _Credentials(),
        http_transport=transport,
        websocket_connect=connect,
    )
    await channel.start()
    await channel.send(_notification(), options={})
    await channel.start_receiving(lambda _message: asyncio.sleep(0))
    await asyncio.wait_for(socket.sent_event.wait(), timeout=1)

    assert channel.receiver_status()["state"] in {"connected", "running"}
    await channel.stop()


@pytest.mark.asyncio
async def test_send_uses_only_config_target_and_official_rest_route():
    transport, requests = _http_transport()
    channel = QQChannel(_config(), _Credentials(), http_transport=transport)
    await channel.start()
    await channel.send(_notification(), options={})

    send_request = requests[-1]
    assert send_request.url.path == "/v2/users/openid-1/messages"
    assert send_request.headers["Authorization"] == "QQBot token-1"
    assert json.loads(send_request.content) == {
        "content": "hello",
        "msg_type": 0,
        "msg_seq": 1,
    }

    with pytest.raises(LogAgentError, match="Workflow 只能设置"):
        await channel.send(_notification(), options={"target_id": "override"})
    await channel.stop()


@pytest.mark.asyncio
async def test_reply_routes_by_explicit_address_and_original_message_id():
    transport, requests = _http_transport()
    channel = QQChannel(_config(), _Credentials(), http_transport=transport)
    await channel.start()
    for kind, target, path in (
        ("c2c", "openid-2", "/v2/users/openid-2/messages"),
        ("group", "group-2", "/v2/groups/group-2/messages"),
    ):
        await channel.reply(
            _notification(),
            address=ChannelAddress(
                kind=kind, target=target, sender="sender-1", message_id="message-1"
            ),
            options={},
        )
        request = requests[-1]
        body = json.loads(request.content)
        assert request.url.path == path
        assert body["msg_id"] == "message-1"
        assert body["msg_seq"] == (1 if kind == "c2c" else 2)

    await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "uncertain"),
    [(400, False), (503, True)],
)
async def test_rest_rejection_and_server_error_report_acceptance(status, uncertain):
    transport, _ = _http_transport(send_status=status)
    channel = QQChannel(_config(), _Credentials(), http_transport=transport)
    await channel.start()
    with pytest.raises(ChannelDeliveryError) as error:
        await channel.send(_notification(), options={})
    assert error.value.uncertain is uncertain
    await channel.stop()


@pytest.mark.asyncio
async def test_send_timeout_is_uncertain_and_not_retried():
    send_calls = 0

    async def timeout(request):
        nonlocal send_calls
        if request.url.host == "bots.qq.com":
            return httpx.Response(200, json={"access_token": "token-1", "expires_in": 7200})
        send_calls += 1
        raise httpx.ReadTimeout("lost response")

    channel = QQChannel(_config(), _Credentials(), http_transport=httpx.MockTransport(timeout))
    await channel.start()
    with pytest.raises(ChannelDeliveryError) as error:
        await channel.send(_notification(), options={})
    assert error.value.uncertain is True
    assert send_calls == 1
    await channel.stop()


@pytest.mark.asyncio
async def test_send_uses_manager_remaining_delivery_budget():
    async def slow_send(request):
        if request.url.host == "bots.qq.com":
            return httpx.Response(200, json={"access_token": "token-1", "expires_in": 7200})
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={"id": "sent-message"})

    channel = QQChannel(_config(), _Credentials(), http_transport=httpx.MockTransport(slow_send))
    await channel.start()
    deadline = asyncio.get_running_loop().time() + 0.02
    token = delivery_deadline.set(deadline)
    try:
        with pytest.raises(ChannelDeliveryError) as error:
            await channel.send(_notification(), options={})
        assert error.value.uncertain is True
        assert asyncio.get_running_loop().time() < deadline + 0.1
    finally:
        delivery_deadline.reset(token)
        await channel.stop()


@pytest.mark.asyncio
async def test_success_status_without_qq_message_id_is_unknown_acceptance():
    async def missing_receipt(_request):
        return httpx.Response(200, json={})

    transport, _ = _http_transport(send_handler=missing_receipt)
    channel = QQChannel(_config(), _Credentials(), http_transport=transport)
    await channel.start()
    with pytest.raises(ChannelDeliveryError) as error:
        await channel.send(_notification(), options={})
    assert error.value.uncertain is True
    assert error.value.code == "qq_send_uncertain"
    await channel.stop()


@pytest.mark.asyncio
async def test_token_expiration_must_be_present_and_valid():
    async def missing_expiration(_request):
        return httpx.Response(200, json={"access_token": "token-1"})

    channel = QQChannel(
        _config(), _Credentials(), http_transport=httpx.MockTransport(missing_expiration)
    )
    await channel.start()
    with pytest.raises(ChannelDeliveryError) as error:
        await channel._get_token()
    assert error.value.code == "qq_authentication_failed"
    await channel.stop()


@pytest.mark.asyncio
async def test_gateway_routes_repeated_events_for_runtime_deduplication():
    group_event = {
        "op": 0,
        "s": 12,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {
            "id": "message-group-1",
            "content": "  hello group  ",
            "group_openid": "group-1",
            "author": {"member_openid": "sender-1"},
        },
    }
    c2c_event = {
        "op": 0,
        "s": 13,
        "t": "C2C_MESSAGE_CREATE",
        "d": {
            "id": "message-c2c-1",
            "content": "hello c2c",
            "author": {"user_openid": "sender-2"},
        },
    }
    socket = _WebSocket(
        [
            {"op": 10, "d": {"heartbeat_interval": 60_000}},
            {
                "op": 0,
                "s": 11,
                "t": "READY",
                "d": {
                    "session_id": "session-1",
                    "user": {"id": "bot-user-id"},
                },
            },
            group_event,
            group_event,
            c2c_event,
        ]
    )
    transport, requests = _http_transport()

    async def connect(url):
        assert url == "wss://gateway.example"
        return socket

    channel = QQChannel(
        _config(), _Credentials(), http_transport=transport, websocket_connect=connect
    )
    delivered = []
    all_received = asyncio.Event()

    async def handler(message: InboundMessage):
        delivered.append(message)
        if len(delivered) == 3:
            all_received.set()

    await channel.start()
    await channel.start_receiving(handler)
    await asyncio.wait_for(all_received.wait(), timeout=1)

    assert socket.sent[0]["op"] == 2
    assert socket.sent[0]["d"]["token"] == "QQBot token-1"
    assert socket.sent[0]["d"]["intents"] & (1 << 25)
    assert [
        (item.address.kind, item.address.target, item.address.sender) for item in delivered
    ] == [
        ("group", "group-1", "sender-1"),
        ("group", "group-1", "sender-1"),
        ("c2c", "sender-2", "sender-2"),
    ]
    assert delivered[0].text == "hello group"
    assert delivered[0].address.message_id == "message-group-1"
    assert channel._bot_user_id == "bot-user-id"
    assert len([request for request in requests if request.url.path == "/gateway"]) == 1
    assert channel.receiver_status()["state"] == "running"

    await channel.stop_receiving()
    await channel.stop()
    assert socket.closed
    assert channel.receiver_status()["state"] == "stopped"


@pytest.mark.parametrize("send_status", [200, 503])
async def test_gateway_message_passes_through_manager_and_real_agent(tmp_path, send_status):
    event = {
        "op": 0, "s": 12, "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {
            "id": "qq-manager-message", "content": "hello Agent",
            "group_openid": "group-1", "author": {"member_openid": "sender-1"},
        },
    }
    socket = _WebSocket([
        {"op": 10, "d": {"heartbeat_interval": 60_000}},
        {"op": 0, "s": 11, "t": "READY", "d": {
            "session_id": "gateway-session", "user": {"id": "bot-user-id"},
        }},
        event, event,
    ])
    transport, requests = _http_transport(send_status=send_status)

    async def connect(_url):
        return socket

    class MockNetworkQQ(QQChannelType):
        async def create(self, config, credentials):
            return QQChannel(
                config, credentials, http_transport=transport, websocket_connect=connect,
            )

    registry = PluginRegistry([], builtin_channels=[MockNetworkQQ()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    model = ScriptedModel(responses=[AIMessage(content="QQ Agent reply")])
    agent = AgentService(
        tmp_path / "workspace", tmp_path / "runtime",
        config=AgentConfig(), model_provider=lambda _: model,
    )
    await agent.initialize()
    manager = ChannelManager(registry.channelRegister, credentials=_Credentials())
    config = _config()
    message = InboundMessage(
        request_id="qq-manager-message", text="hello Agent",
        address=ChannelAddress(
            kind="group", target="group-1", sender="sender-1",
            message_id="qq-manager-message",
        ),
    )
    try:
        await manager.configure_agent(
            AgentChannel(agent), tmp_path / "channels.sqlite3",
        )
        await manager.start_agent([config])
        async with asyncio.timeout(5):
            while True:
                try:
                    outcome = await manager.outcome(config, message)
                except LogAgentError as exc:
                    if exc.code != "request_not_found":
                        raise
                else:
                    if outcome["delivery"] is not None:
                        break
                await asyncio.sleep(0.01)

        assert outcome["response"]["kind"] == "turn"
        assert outcome["status"] == "completed"
        assert len(model.seen) == 1
        sent = [request for request in requests if request.url.path.endswith("/messages")]
        assert len(sent) == 1
        assert sent[0].url.path == "/v2/groups/group-1/messages"
        assert json.loads(sent[0].content)["msg_id"] == "qq-manager-message"
        assert json.loads(sent[0].content)["content"] == "QQ Agent reply"
        if send_status == 200:
            assert outcome["delivery"]["status"] == "success"
        else:
            assert outcome["delivery"]["status"] == "failed"
            assert outcome["delivery"]["error"]["code"] == "qq_send_uncertain"
    finally:
        await manager.close()
        await manager.stop()
        await agent.close()


@pytest.mark.asyncio
async def test_guild_message_strips_only_bot_mention_prefix_for_commands():
    transport, _ = _http_transport()
    channel = QQChannel(_config(), _Credentials(), http_transport=transport)
    channel._bot_user_id = "bot-user-id"
    received = []

    async def handler(message):
        received.append(message)

    channel._handler = handler
    channel._dispatch_message(
        "AT_MESSAGE_CREATE",
        {
            "id": "guild-1",
            "content": "<@!bot-user-id> /stop",
            "channel_id": "channel-1",
            "author": {"id": "user-1"},
        },
    )
    channel._dispatch_message(
        "AT_MESSAGE_CREATE",
        {
            "id": "guild-2",
            "content": "<@!app-1> /stop",
            "channel_id": "channel-1",
            "author": {"id": "user-1"},
        },
    )
    await asyncio.gather(*tuple(channel._handler_tasks))

    assert [message.text for message in received] == [
        "/stop",
        "<@!app-1> /stop",
    ]
    assert received[0].address.message_id == "guild-1"


@pytest.mark.asyncio
async def test_gateway_resume_and_heartbeat_use_official_opcodes():
    transport, _ = _http_transport()
    channel = QQChannel(_config(), _Credentials(), http_transport=transport)
    socket = _WebSocket()
    await channel.start()
    channel._session_id = "gateway-session"
    channel._sequence = 37
    await channel._identify_or_resume(socket)
    assert socket.sent == [
        {
            "op": 6,
            "d": {
                "token": "QQBot token-1",
                "session_id": "gateway-session",
                "seq": 37,
            },
        }
    ]

    channel._receiving = True
    acknowledged = asyncio.Event()
    acknowledged.set()
    heartbeat = asyncio.create_task(channel._heartbeat(socket, 10, acknowledged))
    try:
        async with asyncio.timeout(1):
            while not any(frame["op"] == 1 for frame in socket.sent):
                socket.sent_event.clear()
                await socket.sent_event.wait()
        assert socket.sent[-1] == {"op": 1, "d": 37}
        with pytest.raises(ChannelDeliveryError, match="心跳缺少 ACK"):
            await heartbeat
    finally:
        channel._receiving = False
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
async def test_gateway_consumes_heartbeat_ack_and_surfaces_missing_ack():
    socket = _WebSocket([{"op": 10, "d": {"heartbeat_interval": 10}}])
    transport, _ = _http_transport()

    async def connect(_url):
        return socket

    channel = QQChannel(
        _config(), _Credentials(), http_transport=transport, websocket_connect=connect
    )
    await channel.start()
    channel._receiving = True
    serving = asyncio.create_task(channel._serve_gateway(socket))
    try:
        async with asyncio.timeout(1):
            while not any(frame["op"] == 1 for frame in socket.sent):
                socket.sent_event.clear()
                await socket.sent_event.wait()
        socket.push({"op": 11})
        async with asyncio.timeout(1):
            while sum(frame["op"] == 1 for frame in socket.sent) < 2:
                socket.sent_event.clear()
                await socket.sent_event.wait()
        with pytest.raises(ChannelDeliveryError, match="心跳缺少 ACK"):
            await asyncio.wait_for(serving, timeout=1)
    finally:
        channel._receiving = False
        if not serving.done():
            serving.cancel()
            await asyncio.gather(serving, return_exceptions=True)
        await channel.stop()


@pytest.mark.asyncio
async def test_long_agent_handler_does_not_block_later_stop_message():
    long_started = asyncio.Event()
    release_long = asyncio.Event()
    stop_received = asyncio.Event()
    frames = [
        {"op": 10, "d": {"heartbeat_interval": 60_000}},
        {
            "op": 0,
            "t": "C2C_MESSAGE_CREATE",
            "d": {"id": "long-1", "content": "do work", "author": {"user_openid": "u1"}},
        },
        {
            "op": 0,
            "t": "C2C_MESSAGE_CREATE",
            "d": {"id": "stop-1", "content": "/stop", "author": {"user_openid": "u1"}},
        },
    ]
    socket = _WebSocket(frames)
    transport, _ = _http_transport()

    async def connect(_url):
        return socket

    async def handler(message):
        if message.text == "do work":
            long_started.set()
            await release_long.wait()
        if message.text == "/stop":
            stop_received.set()

    channel = QQChannel(
        _config(), _Credentials(), http_transport=transport, websocket_connect=connect
    )
    await channel.start()
    await channel.start_receiving(handler)
    await asyncio.wait_for(long_started.wait(), timeout=1)
    await asyncio.wait_for(stop_received.wait(), timeout=1)
    release_long.set()
    await channel.stop()


@pytest.mark.asyncio
async def test_stop_receiving_reaps_tasks_when_websocket_close_fails():
    class BrokenCloseWebSocket(_WebSocket):
        async def close(self):
            raise RuntimeError("close failed")

    transport, _ = _http_transport()
    channel = QQChannel(_config(), _Credentials(), http_transport=transport)
    await channel.start()
    channel._receiving = True
    channel._handler = lambda _message: None
    channel._websocket = BrokenCloseWebSocket()
    receiver_gate = asyncio.Event()
    handler_gate = asyncio.Event()
    receiver_task = asyncio.create_task(receiver_gate.wait())
    handler_task = asyncio.create_task(handler_gate.wait())
    channel._receiver_task = receiver_task
    channel._handler_tasks.add(handler_task)

    with pytest.raises(RuntimeError, match="close failed"):
        await channel.stop_receiving()

    assert receiver_task.cancelled()
    assert handler_task.cancelled()
    assert channel._handler is None
    assert channel.receiver_status()["state"] == "stopped"
    await channel.stop()


@pytest.mark.asyncio
async def test_missing_notification_target_fails_before_network_send():
    transport, requests = _http_transport()
    channel = QQChannel(_config(target_kind=None), _Credentials(), http_transport=transport)
    await channel.start()
    with pytest.raises(ChannelDeliveryError, match="target_kind"):
        await channel.send(_notification(), options={})
    assert requests == []
    await channel.stop()
