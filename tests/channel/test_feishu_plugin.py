from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflowweave.channel.conversation import ChannelAddress, InboundMessage
from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.models import ChannelConfig, Notification

_PLUGIN_ROOT = (
    Path(__file__).parents[2]
    / "src"
    / "workflowweave"
    / "plugins"
    / "channel"
    / "feishu"
)


def _load_channel():
    name = "feishu_official_channel_test"
    spec = importlib.util.spec_from_file_location(name, _PLUGIN_ROOT / "channel.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.FeishuChannel, module.FeishuChannelType


class _Credentials:
    async def resolve(self, credential):
        assert credential.kind == "env"
        assert credential.name == "FEISHU_APP_SECRET"
        return "secret-value"


class _OfficialChannel:
    instances: list[_OfficialChannel] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.handlers: dict[str, object] = {}
        self.calls: list[tuple[str, object, object]] = []
        self.connect_calls: list[float | None] = []
        self.disconnect_calls = 0
        self.connected = False
        self.connect_error: BaseException | None = None
        self.disconnect_error: BaseException | None = None
        self.unsubscribe_error: BaseException | None = None
        self.result = SimpleNamespace(success=True, message_id="sent-message")
        self.instances.append(self)

    def on(self, name, callback):
        self.handlers[name] = callback

        def unsubscribe():
            if self.unsubscribe_error is not None:
                raise self.unsubscribe_error
            self.handlers.pop(name, None)

        return unsubscribe

    async def connect_until_ready(self, **kwargs):
        timeout = kwargs.get("timeout")
        self.connect_calls.append(timeout)
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    async def disconnect(self):
        self.disconnect_calls += 1
        if self.disconnect_error is not None:
            raise self.disconnect_error
        self.connected = False

    async def send(self, target, message, options):
        self.calls.append((target, message, options))
        return self.result

    async def emit(self, message):
        callback = self.handlers.get("message")
        assert callback is not None
        return await callback(message)


def _config(**options):
    return ChannelConfig(
        id="feishu-one",
        channel="feishu",
        timeout=1,
        options={
            "app_id": "app-one",
            "app_secret": {"kind": "env", "name": "FEISHU_APP_SECRET"},
            **options,
        },
    )


def _message(
    *, text="hello", sender_type="user", sender_is_bot=False, chat_type="p2p"
):
    return SimpleNamespace(
        message_id="message-one",
        chat_id="chat-one",
        sender_id="open-one",
        body_text=text,
        content_text=text,
        chat_type=chat_type,
        sender_type=sender_type,
        sender_is_bot=sender_is_bot,
        raw_content_type="text",
    )


@pytest.fixture(autouse=True)
def clear_fake_channels():
    _OfficialChannel.instances.clear()


@pytest.mark.asyncio
async def test_send_and_reply_use_official_public_channel_api():
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), channel_factory=_OfficialChannel)
    await channel.start()

    await channel.send(
        Notification(session_id="session-one", output_id="notice", text="notice"),
        options={"target_kind": "chat_id", "target_id": "chat-one"},
    )
    await channel.reply(
        Notification(session_id="session-one", output_id="reply", text="reply"),
        address=ChannelAddress(
            kind="chat_id", target="chat-one", sender="open-one", message_id="original-one"
        ),
        options={},
    )

    sdk = _OfficialChannel.instances[-1]
    assert sdk.calls == [
        ("chat-one", {"text": "notice"}, {"receive_id_type": "chat_id"}),
        (
            "chat-one",
            {"text": "reply"},
            {
                "receive_id_type": "chat_id",
                "reply_to": "original-one",
                "reply_target_gone": "fail",
            },
        ),
    ]
    await channel.stop()


@pytest.mark.asyncio
async def test_rejected_official_send_is_reported_as_delivery_error():
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), channel_factory=_OfficialChannel)
    await channel.start()
    _OfficialChannel.instances[-1].result = SimpleNamespace(
        success=False, error=SimpleNamespace(code="permission_denied")
    )

    with pytest.raises(ChannelDeliveryError) as error:
        await channel.send(
            Notification(session_id="session", output_id="notice", text="hello"),
            options={"target_kind": "chat_id", "target_id": "chat-one"},
        )

    assert error.value.code == "feishu_delivery_rejected"
    assert error.value.details == {"sdk_code": "permission_denied"}
    await channel.stop()


@pytest.mark.asyncio
async def test_official_message_is_normalized_and_admitted_to_manager():
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), channel_factory=_OfficialChannel)
    await channel.start()
    received: list[InboundMessage] = []

    async def admit(message):
        received.append(message)
        return {"status": "accepted"}

    await channel.start_receiving(admit)
    sdk = _OfficialChannel.instances[-1]
    await sdk.emit(_message())

    assert received == [
        InboundMessage(
            request_id="message-one",
            text="hello",
            address=ChannelAddress(
                kind="chat_id",
                target="chat-one",
                sender="open-one",
                message_id="message-one",
                conversation_type="private",
            ),
        )
    ]
    assert sdk.connect_calls == [1]
    assert channel.receiver_status() == {"state": "running", "error": None}
    await channel.stop()
    assert sdk.disconnect_calls == 1
    assert channel.receiver_status() == {"state": "stopped", "error": None}


@pytest.mark.asyncio
async def test_bot_and_empty_messages_are_ignored():
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), channel_factory=_OfficialChannel)
    await channel.start()
    received = []

    async def admit(message):
        received.append(message)
        return {"status": "accepted"}

    await channel.start_receiving(admit)
    sdk = _OfficialChannel.instances[-1]
    await sdk.emit(_message(sender_type="bot"))
    await sdk.emit(_message(sender_is_bot=True))
    await sdk.emit(_message(text="  "))
    media = _message(text="[image]")
    media.raw_content_type = "image"
    await sdk.emit(media)
    assert received == []
    await channel.stop()


@pytest.mark.asyncio
async def test_temporary_receiver_bypasses_persistent_receive_gate():
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(
        _config(receive_events=False), _Credentials(), channel_factory=_OfficialChannel
    )
    await channel.start()
    await channel.start_receiving(lambda _message: asyncio.sleep(0))
    assert channel.receiver_status() == {"state": "stopped", "error": None}

    await channel.start_receiving(lambda _message: asyncio.sleep(0), temporary=True)
    assert channel.receiver_status() == {"state": "running", "error": None}
    await channel.stop_receiving()
    await channel.stop()


@pytest.mark.asyncio
async def test_failed_connect_sets_receiver_failure_and_can_be_stopped():
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), channel_factory=_OfficialChannel)
    await channel.start()
    sdk = _OfficialChannel.instances[-1]
    sdk.connect_error = RuntimeError("connect failed")

    with pytest.raises(RuntimeError, match="connect failed"):
        await channel.start_receiving(lambda _message: asyncio.sleep(0))
    assert channel.receiver_status() == {"state": "failed", "error": "RuntimeError"}
    assert sdk.handlers == {}
    assert sdk.disconnect_calls == 1
    sdk.connect_error = None
    await channel.start_receiving(lambda _message: asyncio.sleep(0))
    await channel.stop()
    assert sdk.disconnect_calls == 2


@pytest.mark.asyncio
async def test_missing_official_dependency_has_explicit_error(monkeypatch):
    FeishuChannel, _ = _load_channel()

    async def missing():
        raise ChannelDeliveryError(
            "feishu_dependency_missing",
            "飞书渠道需要安装 lark-channel-sdk",
            details={"package": "lark-channel-sdk"},
        )

    module_name = "feishu_official_missing_test"
    module = sys.modules[module_name] = sys.modules["feishu_official_channel_test"]
    monkeypatch.setattr(module, "_load_official_sdk", missing)
    channel = FeishuChannel(_config(), _Credentials())
    with pytest.raises(ChannelDeliveryError) as error:
        await channel.start()
    assert error.value.code == "feishu_dependency_missing"
    sys.modules.pop(module_name, None)


@pytest.mark.asyncio
async def test_sdk_background_callback_waits_for_application_loop_admission():
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), channel_factory=_OfficialChannel)
    await channel.start()
    app_loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def admit(message):
        assert asyncio.get_running_loop() is app_loop
        assert message.request_id == "message-one"
        entered.set()
        await release.wait()
        return {"status": "accepted"}

    await channel.start_receiving(admit)
    sdk = _OfficialChannel.instances[-1]

    def emit_from_thread():
        return asyncio.run(sdk.emit(_message()))

    callback = asyncio.create_task(asyncio.to_thread(emit_from_thread))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert not callback.done()
    finally:
        release.set()
        await asyncio.wait_for(callback, timeout=1)
        await channel.stop()


@pytest.mark.asyncio
async def test_old_callback_cannot_enter_a_restarted_receiver():
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), channel_factory=_OfficialChannel)
    await channel.start()
    received = []

    async def admit(message):
        received.append(message)
        return {"status": "accepted"}

    await channel.start_receiving(admit)
    sdk = _OfficialChannel.instances[-1]
    old_callback = sdk.handlers["message"]
    await channel.stop_receiving()
    await channel.start_receiving(admit)
    await old_callback(_message())
    assert received == []
    await sdk.emit(_message())
    assert len(received) == 1
    await channel.stop()


@pytest.mark.asyncio
async def test_cancelled_connect_unsubscribes_and_disconnects():
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), channel_factory=_OfficialChannel)
    await channel.start()
    sdk = _OfficialChannel.instances[-1]
    sdk.connect_error = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await channel.start_receiving(lambda _message: asyncio.sleep(0))
    assert sdk.handlers == {}
    assert sdk.disconnect_calls == 1
    assert channel.receiver_status() == {"state": "stopped", "error": None}
    await channel.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_operation", ["disconnect", "unsubscribe"])
async def test_failed_stop_surfaces_error_and_can_retry(failing_operation):
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), channel_factory=_OfficialChannel)
    await channel.start()
    await channel.start_receiving(lambda _message: asyncio.sleep(0))
    sdk = _OfficialChannel.instances[-1]
    setattr(sdk, f"{failing_operation}_error", RuntimeError("cleanup failed"))
    with pytest.raises(RuntimeError, match="cleanup failed"):
        await channel.stop()
    assert sdk.disconnect_calls == 1
    assert channel.receiver_status() == {"state": "failed", "error": "RuntimeError"}
    setattr(sdk, f"{failing_operation}_error", None)
    await channel.stop()
    assert sdk.handlers == {}
    assert sdk.disconnect_calls == 2
    assert channel.receiver_status() == {"state": "stopped", "error": None}
    await channel.stop()
    assert sdk.disconnect_calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("sdk_code, raw_code, uncertain", [
    ("send_timeout", None, True),
    ("unknown", None, True),
    ("unknown", 1234, False),
    ("permission_denied", None, False),
])
async def test_real_sdk_error_enum_preserves_delivery_certainty(sdk_code, raw_code, uncertain):
    sdk = pytest.importorskip("lark_channel")
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials(), channel_factory=_OfficialChannel)
    await channel.start()
    _OfficialChannel.instances[-1].result = sdk.SendResult.fail(sdk.SendError(
        code=sdk.FeishuChannelErrorCode(sdk_code), retryable=raw_code is None,
        raw_code=raw_code,
    ))
    with pytest.raises(ChannelDeliveryError) as error:
        await channel.send(
            Notification(session_id="session", output_id="notice", text="hello"),
            options={"target_kind": "chat_id", "target_id": "chat-one"},
        )
    assert error.value.uncertain is uncertain
    assert error.value.details == {"sdk_code": sdk_code}
    await channel.stop()


@pytest.mark.asyncio
async def test_real_official_sdk_keeps_messages_separate_and_cleans_background_loop(monkeypatch):
    sdk = pytest.importorskip("lark_channel")
    sdk_module = sys.modules[sdk.FeishuChannel.__module__]
    real_channel = sdk.FeishuChannel

    async def bot_identity(_config):
        return sdk.BotIdentity(open_id="bot-one", name="Test Bot")

    monkeypatch.setattr(sdk_module, "fetch_bot_identity", bot_identity)

    # Exercise the actual SDK lifecycle and dispatcher without a remote account.
    def local_transport(**kwargs):
        return real_channel(**kwargs, transport="webhook")

    monkeypatch.setattr(sdk, "FeishuChannel", local_transport)
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials())
    await channel.start()
    received = []
    app_loop = asyncio.get_running_loop()
    complete = asyncio.Event()

    async def admit(message):
        assert asyncio.get_running_loop() is app_loop
        received.append(message)
        if len(received) == 2:
            complete.set()
        return {"status": "accepted"}

    official = channel._channel
    try:
        assert official.config.policy.require_mention is False
        assert official.config.safety.chat_queue.enabled is False
        assert official.config.outbound.retry.max_attempts == 1
        assert official.config.outbound.text_chunk_limit == 0
        await channel.start_receiving(admit)
        for index in [1, 2]:
            payload = {
                "schema": "2.0",
                "header": {
                    "event_type": "im.message.receive_v1",
                    "event_id": f"event-{index}",
                },
                "event": {
                    "sender": {"sender_type": "user", "sender_id": {"open_id": "open-one"}},
                    "message": {
                        "message_id": f"message-{index}",
                        "chat_id": "chat-one",
                        "chat_type": "p2p",
                        "message_type": "text",
                        "content": json.dumps({"text": f"hello {index}"}),
                        "create_time": str(int(time.time() * 1000)),
                    },
                },
            }
            status, _body = await official.handle_webhook_request(
                headers={}, body=json.dumps(payload).encode(),
            )
            assert status == 200
        await asyncio.wait_for(complete.wait(), timeout=2)
        assert {m.request_id: m.text for m in received} == {
            "message-1": "hello 1", "message-2": "hello 2",
        }
    finally:
        await channel.stop()
    assert official.connection_snapshot().state == "idle"


@pytest.mark.asyncio
@pytest.mark.parametrize("api_code, sdk_code", [(99991402, "rate_limited"), (1234, "unknown")])
async def test_real_official_sender_does_not_retry_or_fall_back_to_fresh_message(
    monkeypatch, api_code, sdk_code,
):
    pytest.importorskip("lark_channel")
    FeishuChannel, _ = _load_channel()
    channel = FeishuChannel(_config(), _Credentials())
    await channel.start()
    official = channel._channel
    reply_calls = []
    create_calls = []

    async def rejected_reply(request):
        reply_calls.append(request.message_id)
        return SimpleNamespace(code=230002, msg="target gone", data=None)

    async def rejected_create(request):
        create_calls.append(request)
        return SimpleNamespace(code=api_code, msg="rejected", data=None)

    monkeypatch.setattr(official.client.im.v1.message, "areply", rejected_reply)
    monkeypatch.setattr(official.client.im.v1.message, "acreate", rejected_create)
    notice = Notification(session_id="session", output_id="notice", text="hello")
    try:
        with pytest.raises(ChannelDeliveryError) as reply_error:
            await channel.reply(
                notice, address=ChannelAddress(
                    kind="chat_id", target="chat-one", sender="open-one", message_id="original",
                ), options={},
            )
        assert reply_error.value.details == {"sdk_code": "target_revoked"}
        assert reply_calls == ["original"]
        assert create_calls == []
        with pytest.raises(ChannelDeliveryError) as send_error:
            await channel.send(notice, options={"target_kind": "chat_id", "target_id": "chat-one"})
        assert send_error.value.details == {"sdk_code": sdk_code}
        assert send_error.value.uncertain is False
        assert len(create_calls) == 1
    finally:
        await channel.stop()


def test_channel_type_maps_only_private_chat_addresses():
    _, channel_type = _load_channel()
    instance = channel_type()
    private = ChannelAddress(
        kind="chat_id", target="chat-one", sender="open-one", message_id="message-one",
        conversation_type="private",
    )
    group = private.model_copy(update={"conversation_type": "group"})
    assert instance.connection_options(private) == {
        "target_kind": "chat_id", "target_id": "chat-one"
    }
    assert instance.connection_options(group) is None
