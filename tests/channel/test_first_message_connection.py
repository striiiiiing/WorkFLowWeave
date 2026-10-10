"""Connection admission uses real Manager ownership and real resource publication."""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from workflowweave.channel import ChannelManager
from workflowweave.channel.connection import ChannelConnections
from workflowweave.channel.conversation import ChannelAddress, InboundMessage
from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.config.store import ResourceStore
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import CapabilityDescription, ChannelConfig, Notification


class Receiver:
    def __init__(self):
        self.handler = None
        self.receiving = 0
        self.stopped = 0
        self.sent = []
        self.reply_error = None
        self.start_error = None
        self.stop_error = None
        self.send_entered = asyncio.Event()
        self.send_release = asyncio.Event()
        self.send_release.set()
        self.state = "stopped"

    async def start(self):
        pass

    async def stop(self):
        await self.stop_receiving()

    async def start_receiving(self, handler, *, temporary=False):
        if self.start_error:
            raise self.start_error
        assert self.handler is None, "a second receiver was started"
        self.handler = handler
        self.receiving += 1
        self.state = "running"

    async def stop_receiving(self):
        if self.handler:
            self.stopped += 1
        self.handler = None
        self.state = "stopped"
        if self.stop_error:
            raise self.stop_error

    def receiver_status(self):
        return {"state": self.state, "error": None}

    async def reply(self, notification, *, address, options):
        self.send_entered.set()
        await self.send_release.wait()
        if self.reply_error:
            raise self.reply_error
        self.sent.append((notification.text, address, dict(options)))

    async def send(self, notification, *, options):
        self.sent.append((notification.text, None, dict(options)))


class Type:
    name = "test"
    capabilities = ["notification", "conversation"]
    options_schema = {"type": "object", "additionalProperties": False, "properties": {
        "account": {"type": "string", "description": "account"},
        "target": {"type": "string", "description": "target", "x-workflowweave-workflow": True},
    }}

    def __init__(self, receiver):
        self.receiver = receiver

    def connection_options(self, address):
        return {"target": address.target} if address.conversation_type == "private" else None

    async def create(self, config, credentials):
        return self.receiver


class Register:
    def __init__(self, receiver):
        self.type = Type(receiver)

    def get(self, name):
        return self.type if name == "test" else None

    def describe(self):
        return [CapabilityDescription(
            kind="channel", name="test", description="test channel", plugin="test",
            capabilities=self.type.capabilities, options_schema=self.type.options_schema,
        )]


def message(ident="first", *, private=True):
    return InboundMessage(request_id=ident, text="hello", address=ChannelAddress(
        kind="test", target="chat", sender="user", message_id=ident,
        conversation_type="private" if private else "group",
    ))


def setup(tmp_path, *, agent=False, timeout=1):
    receiver = Receiver()
    manager = ChannelManager(Register(receiver))
    manager.connections = ChannelConnections(manager, timeout=timeout)
    config = ChannelConfig(id="bot", channel="test", options={"account": "one"},
                           agent_enabled=agent, timeout=1)
    store = ResourceStore(tmp_path / "resources.json", channel_register=Register(receiver))
    store.save("channels", config)

    async def persist(expected, target):
        return store.save_if_current("channels", expected, expected.model_copy(update={
            "options": {**expected.options, **target},
        }))

    return manager, receiver, config, store, persist


async def wait_state(manager, state):
    for _ in range(2000):
        if manager.connections.snapshot("bot")["state"] == state:
            return
        await asyncio.sleep(.001)
    raise AssertionError(f"state did not reach {state}")


async def test_single_direction_captures_private_target_confirms_once_and_stops(tmp_path):
    manager, receiver, config, store, persist = setup(tmp_path)
    try:
        assert (await manager.connections.start(config, persist))["state"] == "connecting"
        await wait_state(manager, "waiting_message")
        assert (await manager.connections.start(config, persist))["state"] == "waiting_message"
        assert await receiver.handler(message(private=False)) == {
            "status": "ignored", "reason": "private_message_required",
        }
        receiver.send_release.clear()
        inbound = message()
        assert await receiver.handler(inbound) == {"status": "accepted"}
        await receiver.send_entered.wait()
        assert await receiver.handler(inbound) == {"status": "duplicate"}
        assert "target" not in store.get("channels", "bot").options
        receiver.send_release.set()
        await wait_state(manager, "connected")
        assert receiver.sent == [("成功连接", inbound.address, {"target": "chat"})]
        assert store.get("channels", "bot").options["target"] == "chat"
        assert receiver.receiving == 1 and receiver.stopped == 1 and receiver.handler is None
        result = await manager.send(store.get("channels", "bot"), Notification(
            session_id="workflow", output_id="notice", text="notification",
        ))
        assert result.status == "success" and receiver.receiving == 1
    finally:
        receiver.send_release.set()
        await manager.stop()


async def test_duplex_reuses_receiver_and_passes_later_messages_to_agent(tmp_path):
    manager, receiver, config, store, persist = setup(tmp_path, agent=True)
    manager.enqueue = AsyncMock(return_value={"status": "accepted"})
    try:
        await manager.configure([config])
        await manager.connections.start(config, persist)
        await wait_state(manager, "waiting_message")
        await receiver.handler(message())
        await wait_state(manager, "connected")
        assert receiver.receiving == 1 and receiver.stopped == 0
        saved = store.get("channels", "bot")
        await manager.configure([saved])
        assert await receiver.handler(message()) == {"status": "duplicate"}
        await receiver.handler(message("later"))
        assert manager.enqueue.await_count == 1
        assert manager.enqueue.await_args.args[:2] == ("bot", message("later"))
    finally:
        await manager.stop()


@pytest.mark.parametrize("error", [
    ChannelDeliveryError("rejected", "rejected"),
    ChannelDeliveryError("uncertain", "uncertain", uncertain=True),
])
async def test_confirmation_failure_is_explicit_and_does_not_save_or_retry(tmp_path, error):
    manager, receiver, config, store, persist = setup(tmp_path)
    receiver.reply_error = error
    try:
        await manager.connections.start(config, persist)
        await wait_state(manager, "waiting_message")
        await receiver.handler(message())
        await wait_state(manager, "failed")
        await manager.connections._sessions["bot"].task
        assert manager.connections.snapshot("bot")["error"]["code"] == error.code
        assert receiver.sent == [] and receiver.stopped == 1
        assert "target" not in store.get("channels", "bot").options
    finally:
        await manager.stop()


async def test_platform_message_id_does_not_become_internal_output_id(tmp_path, caplog):
    manager, receiver, config, store, persist = setup(tmp_path)
    try:
        caplog.set_level(logging.INFO, logger="workflowweave")
        await manager.connections.start(config, persist)
        await wait_state(manager, "waiting_message")
        await receiver.handler(message("qq-message:with/remote-format"))
        await wait_state(manager, "connected")
        assert receiver.sent == [("成功连接", message("qq-message:with/remote-format").address,
                                  {"target": "chat"})]
        assert store.get("channels", "bot").options["target"] == "chat"
        events = {record.__dict__.get("event") for record in caplog.records}
        assert {
            "channel_connection_message_received",
            "channel_connection_confirmation_result",
            "channel_connection_target_saved",
            "channel_connection_result",
        } <= events
        assert "hello" not in caplog.text
    finally:
        await manager.stop()


async def test_cleanup_failure_does_not_replace_confirmation_error(tmp_path):
    manager, receiver, config, store, persist = setup(tmp_path)
    receiver.reply_error = ChannelDeliveryError("qq_send_failed", "QQ 消息发送失败")
    receiver.stop_error = WorkFLowWeaveError("receiver_stop_failed", "接收器停止失败")
    try:
        await manager.connections.start(config, persist)
        await wait_state(manager, "waiting_message")
        await receiver.handler(message("qq-message:123"))
        await wait_state(manager, "failed")
        session = manager.connections._sessions["bot"]
        await session.task
        assert session.error.code == "qq_send_failed"
        assert session.error.details["cleanup_error"]["code"] == "channel_connection_cleanup_failed"
        assert "target" not in store.get("channels", "bot").options
    finally:
        receiver.stop_error = None
        await manager.stop()


async def test_cancel_before_task_starts_and_timeout_reclaim_receiver(tmp_path):
    manager, receiver, config, _, persist = setup(tmp_path, timeout=.03)
    try:
        await manager.connections.start(config, persist)
        assert (await manager.connections.cancel("bot"))["state"] == "cancelled"
        await manager.connections.start(config, persist)
        await wait_state(manager, "failed")
        await manager.connections._sessions["bot"].task
        assert manager.connections.snapshot("bot")["error"]["code"] == "channel_connection_timeout"
        assert receiver.handler is None
    finally:
        await manager.stop()


async def test_config_change_cancels_old_wait_and_compare_and_save_rejects_stale_result(tmp_path):
    manager, receiver, config, store, persist = setup(tmp_path)
    try:
        await manager.connections.start(config, persist)
        await wait_state(manager, "waiting_message")
        changed = config.model_copy(update={"options": {"account": "two"}})
        store.save("channels", changed)
        await manager.configure([changed])
        assert receiver.handler is None and manager.connections.snapshot("bot")["state"] == "idle"
        with pytest.raises(WorkFLowWeaveError, match="资源已变更"):
            await persist(config, {"target": "old"})
        assert store.get("channels", "bot") == changed
    finally:
        await manager.stop()


async def test_startup_failure_and_shutdown_are_observable(tmp_path):
    manager, receiver, config, _, persist = setup(tmp_path)
    receiver.start_error = ChannelDeliveryError("auth_failed", "认证失败")
    await manager.connections.start(config, persist)
    await wait_state(manager, "failed")
    assert manager.connections.snapshot("bot")["error"]["code"] == "auth_failed"
    receiver.start_error = None
    await manager.connections.start(config, persist)
    await wait_state(manager, "waiting_message")
    await manager.stop()
    assert manager.connections.snapshot("bot")["state"] == "cancelled"
    assert receiver.handler is None
