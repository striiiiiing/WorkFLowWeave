"""SDK 受理与 Agent 执行的边界：真实 Manager/AgentService、阻塞端口及原路回复。"""

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from tests.agent.helpers import ScriptedModel
from tests.fixtures.channels import TestChannelType
from workflowweave.agent.commands import AgentCommand, CommandDispatcher
from workflowweave.agent.config import AgentConfig
from workflowweave.channel import ChannelManager
from workflowweave.channel.conversation import ChannelAddress, InboundMessage
from workflowweave.config import PluginRegistry
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.interaction.fastapi.agent import create_agent_service
from workflowweave.models import ChannelConfig, Notification, SystemConfig


async def test_platform_ack_precedes_agent_processing_and_reply_uses_original_route(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="answer")])
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", config=AgentConfig(),
                           model_provider=lambda _: model)
    await service.initialize()
    registry = PluginRegistry(builtin_channels=[TestChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    manager = ChannelManager(registry.channelRegister)
    entered = asyncio.Event()
    release = asyncio.Event()

    class PausedPort(CommandDispatcher):
        async def dispatch(self, command, *, valid=None):
            entered.set()
            await release.wait()
            return await super().dispatch(command, valid=valid)

    config = ChannelConfig(id="test", channel="test", agent_enabled=True)
    await manager.configure_agent(PausedPort(service), tmp_path / "bindings.sqlite3")
    await manager.start_agent([config])
    receiver = manager.receiver(config)
    message = InboundMessage(request_id="sdk-event", text="hello", address=ChannelAddress(
        kind="test", target="group", sender="alice", message_id="sdk-event",
    ))
    try:
        # A one-way notification never reaches the Agent processing port.
        receipt = await manager.send(config, Notification(
            session_id="workflow", output_id="report", text="scheduled",
        ))
        assert receipt.status == "success"
        assert not entered.is_set() and not service.sessions

        created = await CommandDispatcher(service).dispatch(AgentCommand(
            channel="web", request_id="initial-session", text="/new",
        ))
        await manager.bind_conversation(config.id, created["result"]["session_id"])
        assert await asyncio.wait_for(receiver.handler(message), 2) == {"status": "accepted"}
        await asyncio.wait_for(entered.wait(), 2)
        assert len(service.sessions) == 1
        assert not model.seen
        assert await asyncio.wait_for(receiver.handler(message), 2) == {"status": "duplicate"}
        with pytest.raises(WorkFLowWeaveError) as conflict:
            await receiver.handler(message.model_copy(update={"text": "different"}))
        assert conflict.value.code == "request_conflict"

        release.set()
        assert await manager._input_queue.drain(5) == 0
        outcome = await manager.outcome(config, message)
        assert outcome["delivery"]["status"] == "success"
        assert len(service.sessions) == 1
        assert [entry["notification"]["text"] for entry in receiver.outbox()] == [
            "scheduled", "answer",
        ]
        assert receiver.outbox()[-1]["address"] == message.address.model_dump()
        assert await receiver.handler(message) == {"status": "duplicate"}
    finally:
        release.set()
        await manager.close()
        await manager.stop()
        await service.close()


@pytest.mark.parametrize("platform,private", [
    ("qq", True), ("qq", False), ("feishu", True), ("feishu", False),
    ("telegram", True), ("telegram", False), ("wechat_openclaw", True),
])
async def test_each_plugin_inbound_callback_enters_manager_and_replies_once(
    tmp_path, platform, private,
):
    module = importlib.import_module(f"workflowweave.plugins.channel.{platform}.channel")
    class_name = {"qq": "QQ", "feishu": "Feishu", "telegram": "Telegram",
                  "wechat_openclaw": "WechatOpenClaw"}[platform]
    channel_type = getattr(module, f"{class_name}ChannelType")()
    options = {
        "qq": {"app_id": "app", "client_secret": {"kind": "env", "name": "QQ_SECRET"}},
        "feishu": {"app_id": "app", "app_secret": {"kind": "env", "name": "FEISHU_SECRET"}},
        "telegram": {"token": {"kind": "env", "name": "TELEGRAM_TOKEN"}},
        "wechat_openclaw": {"account_id": "account"},
    }[platform]
    config = ChannelConfig(id=platform, channel=platform, options=options, agent_enabled=True)
    channel = await channel_type.create(config, None)

    async def start_receiving(handler):
        channel._handler = handler
        if platform == "feishu":
            channel._receiving = True

    async def stop_receiving():
        channel._handler = None

    # SDK lifecycle/routing have separate contract tests. Here only transport
    # I/O is replaced; the concrete inbound normalizer and Manager stay real.
    channel.start = AsyncMock()
    channel.stop = AsyncMock()
    channel.start_receiving = start_receiving
    channel.stop_receiving = stop_receiving
    channel.reply = AsyncMock()
    channel._write = AsyncMock()  # Capture the Weixin IPC admission ACK.

    async def create(_config, _credentials):
        return channel

    channel_type.create = create
    registry = PluginRegistry(builtin_channels=[channel_type])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    model = ScriptedModel(responses=[AIMessage(content="reply")])
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", config=AgentConfig(),
                           model_provider=lambda _: model)
    await service.initialize()
    manager = ChannelManager(registry.channelRegister)
    await manager.configure_agent(CommandDispatcher(service), tmp_path / "bindings.sqlite3")
    await manager.start_agent([config])
    created = await CommandDispatcher(service).dispatch(AgentCommand(
        channel="web", request_id="initial-session", text="/new",
    ))
    await manager.bind_conversation(config.id, created["result"]["session_id"])

    async def emit():
        if platform == "qq":
            await channel._emit_message("c2c" if private else "group", SimpleNamespace(
                id="event", content="hello", group_openid="group",
                author=SimpleNamespace(id="numeric-id", user_openid="sender") if private
                else SimpleNamespace(id="sender"),
            ))
        elif platform == "feishu":
            await channel._on_message(SimpleNamespace(
                message_id="event", chat_id="group", sender_id="sender",
                chat_type="p2p" if private else "group", body_text="hello",
                sender_type="user", sender_is_bot=False, raw_content_type="text",
            ), loop=asyncio.get_running_loop(), generation=channel._receiver_generation)
        elif platform == "telegram":
            await channel._on_update(SimpleNamespace(
                effective_message=SimpleNamespace(message_id=7, text="hello"),
                effective_chat=SimpleNamespace(
                    id=8 if private else -99,
                    type="private" if private else "supergroup",
                ),
                effective_user=SimpleNamespace(id=8),
            ))
        else:
            await channel._handle_inbound({"message_id": "event", "text": "hello",
                "conversation_kind": "weixin", "conversation_id": "group", "sender_id": "sender"})

    try:
        await emit()
        assert await manager._input_queue.drain(5) == 0
        await emit()  # A repeated SDK event must not produce another Agent turn or reply.
        assert await manager._input_queue.drain(5) == 0
        assert len(model.seen) == 1 and len(service.sessions) == 1
        channel.reply.assert_awaited_once()
        args, kwargs = channel.reply.await_args
        assert args[0].text == "reply"
        address = kwargs["address"]
        target = (
            "sender" if platform == "qq" and private
            else "8" if platform == "telegram" and private
            else "-99" if platform == "telegram"
            else "group"
        )
        assert (address.target, address.sender, address.message_id) == (
            (target, "8", "7") if platform == "telegram" else (target, "sender", "event")
        )
        if platform in {"qq", "feishu"} and private:
            assert "target_id" not in config.options and "target_kind" not in config.options
            assert address.kind == ("c2c" if platform == "qq" else "chat_id")
        if platform in {"qq", "feishu", "telegram"}:
            assert channel_type.options_schema["x-workflowweave-first-message"] is True
            expected_target = None
            if private and platform == "qq":
                expected_target = {"target_kind": "c2c", "target_id": "sender"}
            elif private and platform == "feishu":
                expected_target = {"target_kind": "chat_id", "target_id": "group"}
            elif private and platform == "telegram":
                expected_target = {"chat_id": 8}
            assert channel_type.connection_options(address) == expected_target
        if platform == "wechat_openclaw":
            assert [call.args[0]["status"] for call in channel._write.await_args_list] == [
                "accepted", "duplicate",
            ]
    finally:
        await manager.close()
        await manager.stop()
        await service.close()
