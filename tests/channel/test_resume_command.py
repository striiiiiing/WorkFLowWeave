"""History listing and explicit resume through real shared channel boundaries."""

import asyncio

import httpx
import pytest
from langchain_core.messages import AIMessage

from tests.agent.test_admission import GatedModel
from tests.fixtures.channels import TestChannelType
from workflowweave.agent.commands import CommandDispatcher
from workflowweave.channel import ChannelManager
from workflowweave.channel.conversation import ChannelAddress, InboundMessage
from workflowweave.config import PluginRegistry
from workflowweave.interaction.app import create_app
from workflowweave.interaction.fastapi.agent import create_agent_service
from workflowweave.lifecycle import ApplicationLifecycle
from workflowweave.models import ChannelConfig, SystemConfig


@pytest.fixture
async def channel_runtime(tmp_path):
    model = GatedModel(responses=[AIMessage(content="完成")])
    service = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model,
    )
    await service.initialize()
    registry = PluginRegistry(builtin_channels=[TestChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    manager = ChannelManager(registry.channelRegister)
    config = ChannelConfig(id="test", channel="test", agent_enabled=True)
    await manager.configure_agent(CommandDispatcher(service), tmp_path / "bindings.sqlite3")
    await manager.start_agent([config])
    try:
        yield service, manager, config, model
    finally:
        model.release.set()
        await manager.close()
        await manager.stop()
        await service.close()


def inbound(request_id, text):
    return InboundMessage(request_id=request_id, text=text, address=ChannelAddress(
        kind="test", target="room", sender="alice", message_id=request_id,
    ))


async def reply_outcome(manager, config, message):
    async with asyncio.timeout(2):
        while True:
            outcome = await manager.outcome(config, message)
            if outcome["delivery"] is not None:
                assert outcome["delivery"]["status"] == "success"
                return outcome["response"]
            await asyncio.sleep(0.005)


async def test_channel_resume_lists_history_without_binding_and_explicit_id_binds(channel_runtime):
    service, manager, config, model = channel_runtime
    receiver = manager.receiver(config)
    empty = inbound("empty", "/resume")
    initial_binding = manager.bindings.instance(config.id)
    assert await receiver.inject(empty) == {"status": "accepted"}
    empty_response = await reply_outcome(manager, config, empty)
    assert empty_response["kind"] == "sessions"
    assert empty_response["result"] == []
    assert receiver.outbox()[-1]["notification"]["text"] == "暂无历史对话。使用 /new 创建对话。"
    assert manager.bindings.instance(config.id) == initial_binding

    first = await service.create_session()
    second = await service.create_session()
    await service.set_title(first["session_id"], "生产告警复盘")
    for bound in (False, True):
        if bound:
            await manager.bind_conversation(config.id, first["session_id"])
        binding = manager.bindings.instance(config.id)
        message = inbound(f"list-{bound}", "/resume")
        assert await receiver.inject(message) == {"status": "accepted"}
        response = await reply_outcome(manager, config, message)
        assert response["kind"] == "sessions"
        assert response["result"] == await service.list_sessions()
        assert manager.bindings.instance(config.id) == binding
        text = receiver.outbox()[-1]["notification"]["text"]
        assert "生产告警复盘" in text and "未命名对话" in text
        assert f"/resume {first['session_id']}" in text
        assert f"/resume {second['session_id']}" in text
        assert receiver.outbox()[-1]["address"] == message.address.model_dump()

    before_duplicate = len(receiver.outbox())
    assert await receiver.inject(message) == {"status": "duplicate"}
    assert len(receiver.outbox()) == before_duplicate

    resume = inbound("resume", f"/resume    {second['session_id']}")
    assert await receiver.inject(resume) == {"status": "accepted"}
    response = await reply_outcome(manager, config, resume)
    assert response["kind"] == "session"
    assert response["result"] == second
    assert manager.bindings.instance(config.id).session_id == second["session_id"]

    binding = manager.bindings.instance(config.id)
    missing = inbound("missing", "/resume missing-session")
    assert await receiver.inject(missing) == {"status": "accepted"}
    rejected = await reply_outcome(manager, config, missing)
    assert rejected["error"]["code"] == "session_not_found"
    assert manager.bindings.instance(config.id) == binding
    assert not model.seen


async def test_resume_listing_does_not_wait_for_an_active_turn(channel_runtime):
    service, manager, config, model = channel_runtime
    created = await service.create_session()
    await manager.bind_conversation(config.id, created["session_id"])
    binding = manager.bindings.instance(config.id)
    receiver = manager.receiver(config)
    assert await receiver.inject(inbound("running", "请分析")) == {"status": "accepted"}
    await asyncio.wait_for(model.entered.wait(), 2)

    message = inbound("list-running", "/resume")
    assert await receiver.inject(message) == {"status": "accepted"}
    response = await reply_outcome(manager, config, message)
    assert response["kind"] == "sessions"
    assert response["result"][0]["status"] == "running"
    assert not model.release.is_set()
    assert manager.bindings.instance(config.id) == binding


async def test_invalid_stop_argument_does_not_cancel_active_turn(channel_runtime):
    service, manager, config, model = channel_runtime
    created = await service.create_session()
    await manager.bind_conversation(config.id, created["session_id"])
    receiver = manager.receiver(config)
    assert await receiver.inject(inbound("running-stop", "请分析")) == {"status": "accepted"}
    await asyncio.wait_for(model.entered.wait(), 2)
    turn_id = service.turns.current(created["session_id"]).turn_id

    invalid = inbound("invalid-stop", "/stop wrong")
    assert await receiver.inject(invalid) == {"status": "accepted"}
    response = await reply_outcome(manager, config, invalid)
    assert response["kind"] == "error"
    assert response["error"]["code"] == "invalid_argument"
    assert "直接输入 /stop" in response["error"]["message"]
    assert not model.release.is_set()

    model.release.set()
    await asyncio.wait_for(service.wait(turn_id), 2)


@pytest.mark.parametrize("endpoint", ["/api/channels/web/commands", "/api/agents/commands"])
async def test_resume_http_lists_history_and_only_explicit_id_returns_a_session(tmp_path, endpoint):
    lifecycle = ApplicationLifecycle(SystemConfig(
        data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"),
    ), channel_factories={})
    app = create_app(lifecycle)
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        empty = await client.post(endpoint, json={"text": "/resume", "request_id": "empty"})
        assert empty.status_code == 202
        assert empty.json()["kind"] == "sessions"
        assert empty.json()["result"] == []
        first = await client.post("/api/agents/sessions", json={})
        second = await client.post("/api/agents/sessions", json={})
        assert first.status_code == second.status_code == 201
        first_id, second_id = first.json()["session_id"], second.json()["session_id"]

        listed = await client.post(endpoint, json={
            "session": first_id, "text": "/resume", "request_id": "list",
        })
        assert listed.status_code == 202
        assert listed.json()["kind"] == "sessions"
        assert listed.json()["result"] == (await client.get("/api/agents/sessions")).json()
        assert {item["session_id"] for item in listed.json()["result"]} == {first_id, second_id}

        workflows = await client.post(endpoint, json={"text": "/workflow", "request_id": "workflows"})
        assert workflows.status_code == 202
        assert workflows.json()["kind"] == "workflows"
        assert workflows.json()["result"] == []

        resumed = await client.post(endpoint, json={
            "session": first_id, "text": f"/resume {second_id}", "request_id": "resume",
        })
        assert resumed.status_code == 202
        assert resumed.json()["kind"] == "session"
        assert resumed.json()["result"]["session_id"] == second_id
