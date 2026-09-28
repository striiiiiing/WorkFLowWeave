"""Agent duplex transport contract tests using the builtin local test channel."""

import asyncio
from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage
from pydantic import Field

from logagent.agent.commands import AgentCommand
from logagent.agent.config import AgentConfig
from logagent.agent.service import AgentService
from logagent.channel import ChannelManager
from logagent.channel.bindings import ChannelBindings
from logagent.channel.testing import TestChannelType
from logagent.collection import CollectorManager, MockCollector
from logagent.config import PluginRegistry
from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    AnalysisResult,
    AnalysisTask,
    ChannelConfig,
    Notification,
    SourceConfig,
    SystemConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)
from logagent.workflow.execution.runner import WorkflowRunner
from tests.agent.helpers import ScriptedModel


def _config(*, enabled=True, agent_enabled=True, target="local"):
    return ChannelConfig(
        id="test",
        channel="test",
        options={"target": target},
        enabled=enabled,
        agent_enabled=agent_enabled,
    )


async def _registry(tmp_path):
    registry = PluginRegistry([], builtin_channels=[TestChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    return registry


async def _agent(tmp_path, model):
    service = AgentService(
        tmp_path / "workspace",
        tmp_path / "runtime",
        config=AgentConfig(),
        model_provider=lambda _: model,
    )
    await service.initialize()
    return service


def _message(request_id, text, *, sender="alice", target="room", kind="test"):
    from logagent.channel.conversation import ChannelAddress, InboundMessage

    return InboundMessage(
        request_id=request_id,
        text=text,
        address=ChannelAddress(
            kind=kind,
            target=target,
            sender=sender,
            message_id=f"message-{request_id}",
        ),
    )


async def _settle_reply(runtime, receiver, request_id, *, sender="alice", target="room", kind="test"):
    result = await runtime.outcome(
        runtime.configs["test"],
        _message(request_id, "placeholder", sender=sender, target=target, kind=kind),
    )
    assert result["response"] is not None
    for _ in range(200):
        if result["delivery"] is not None:
            return result
        await asyncio.sleep(0.005)
        result = await runtime.outcome(
            runtime.configs["test"],
            _message(request_id, "placeholder", sender=sender, target=target, kind=kind),
        )
    pytest.fail("Agent channel reply was not delivered")


async def _start(tmp_path, model, config=None):
    service = await _agent(tmp_path, model)
    registry = await _registry(tmp_path)
    channels = ChannelManager(registry.channelRegister)
    await channels.configure_agent(
        _AgentCommands(service), tmp_path / "agents" / "channels.sqlite3",
    )
    await channels.start_agent([config or _config()])
    return service, channels, channels


class _AgentCommands:
    """Production command adapter, keeping tests on real AgentService operations."""

    def __init__(self, service):
        from logagent.channel.agent import AgentChannel

        self._channel = AgentChannel(service)

    async def dispatch(self, command, *, valid=None):
        return await self._channel.dispatch(command, valid=valid)

    async def wait(self, turn_id):
        return await self._channel.wait(turn_id)

    async def wait_command(self, session_id, *, request_id=None, event_id=None):
        return await self._channel.wait_command(
            session_id, request_id=request_id, event_id=event_id,
        )

    async def recover_request(self, operation_id, *, channel, operation):
        return await self._channel.recover_request(
            operation_id, channel=channel, operation=operation,
        )

    async def recover_initial_session(self, operation_id):
        return await self._channel.recover_initial_session(operation_id)


async def _close(service, channels, runtime):
    await channels.close()
    await channels.stop()
    await service.close()


async def test_first_message_creates_session_and_later_messages_share_context(tmp_path):
    model = ScriptedModel(responses=[
        AIMessage(content="first answer"),
        AIMessage(content="second answer"),
    ])
    service, channels, runtime = await _start(tmp_path, model)
    try:
        receiver = channels.receiver(runtime.configs["test"])
        first = await receiver.inject(_message("one", "remember this"))
        await service.wait(first["result"]["turn_id"])
        await _settle_reply(runtime, receiver, "one")

        second = await receiver.inject(_message("two", "what did I say?"))
        await service.wait(second["result"]["turn_id"])
        await _settle_reply(runtime, receiver, "two")

        assert first["result"]["session_id"] == second["result"]["session_id"]
        assert [message.content for message in model.seen[1] if hasattr(message, "content")] \
            .count("remember this") == 1
        assert [entry["notification"]["text"] for entry in receiver.outbox()] == [
            "first answer", "second answer",
        ]
    finally:
        await _close(service, channels, runtime)


async def test_each_sender_gets_an_independent_agent_session(tmp_path):
    model = ScriptedModel(responses=[
        AIMessage(content="alice"), AIMessage(content="bob"),
    ])
    service, channels, runtime = await _start(tmp_path, model)
    try:
        receiver = channels.receiver(runtime.configs["test"])
        alice = await receiver.inject(_message("alice-1", "for alice", sender="alice"))
        await service.wait(alice["result"]["turn_id"])
        await _settle_reply(runtime, receiver, "alice-1", sender="alice")
        bob = await receiver.inject(_message("bob-1", "for bob", sender="bob"))
        await service.wait(bob["result"]["turn_id"])
        await _settle_reply(runtime, receiver, "bob-1", sender="bob")
        assert alice["result"]["session_id"] != bob["result"]["session_id"]
        assert [entry["notification"]["text"] for entry in receiver.outbox()] == ["alice", "bob"]
    finally:
        await _close(service, channels, runtime)


async def test_request_id_is_idempotent_and_rejects_different_content(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="answer")])
    service, channels, runtime = await _start(tmp_path, model)
    try:
        receiver = channels.receiver(runtime.configs["test"])
        message = _message("same-id", "hello")
        first = await receiver.inject(message)
        await service.wait(first["result"]["turn_id"])
        await _settle_reply(runtime, receiver, "same-id")

        duplicate = await receiver.inject(message)
        with pytest.raises(LogAgentError) as conflict:
            await receiver.inject(_message("same-id", "different"))

        assert duplicate["deduplicated"] is True
        assert conflict.value.code == "request_conflict"
        assert len(model.seen) == 1
        assert [entry["notification"]["text"] for entry in receiver.outbox()] == ["answer"]
    finally:
        await _close(service, channels, runtime)


async def test_new_and_resume_enforce_peer_session_ownership(tmp_path):
    model = ScriptedModel(responses=[])
    service, channels, runtime = await _start(tmp_path, model)
    try:
        receiver = channels.receiver(runtime.configs["test"])
        created = await receiver.inject(_message("new-a", "/new", sender="alice"))
        session_id = created["result"]["session_id"]
        own_resume = await receiver.inject(
            _message("resume-a", f"/resume {session_id}", sender="alice")
        )
        foreign_resume = await receiver.inject(
            _message("resume-b", f"/resume {session_id}", sender="bob")
        )
        assert own_resume["kind"] == "session"
        assert own_resume["result"]["session_id"] == session_id
        assert foreign_resume["kind"] == "error"
        assert foreign_resume["error"]["code"] == "session_forbidden"
    finally:
        await _close(service, channels, runtime)


async def test_binding_survives_runtime_restart(tmp_path):
    model = ScriptedModel(responses=[
        AIMessage(content="before restart"), AIMessage(content="after restart"),
    ])
    service, channels, runtime = await _start(tmp_path, model)
    receiver = channels.receiver(runtime.configs["test"])
    try:
        first = await receiver.inject(_message("before", "first"))
        await service.wait(first["result"]["turn_id"])
        await _settle_reply(runtime, receiver, "before")
        bound_session = first["result"]["session_id"]
        await channels.close()
        await channels.stop()
        await service.close()

        service = await _agent(tmp_path, model)
        channels = ChannelManager((await _registry(tmp_path)).channelRegister)
        await channels.configure_agent(
            _AgentCommands(service), tmp_path / "agents" / "channels.sqlite3",
        )
        await channels.start_agent([_config()])
        runtime = channels
        receiver = channels.receiver(runtime.configs["test"])
        second = await receiver.inject(_message("after", "continue"))
        await service.wait(second["result"]["turn_id"])
        await _settle_reply(runtime, receiver, "after")
        assert second["result"]["session_id"] == bound_session
    finally:
        await _close(service, channels, runtime)


async def test_stop_interrupts_active_model_turn(tmp_path):
    class WaitingModel(ScriptedModel):
        started: asyncio.Event = Field(default_factory=asyncio.Event)

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.seen.append(list(messages))
            self.started.set()
            await asyncio.Future()

    model = WaitingModel(responses=[])
    service, channels, runtime = await _start(tmp_path, model)
    try:
        receiver = channels.receiver(runtime.configs["test"])
        accepted = await receiver.inject(_message("running", "long request"))
        await asyncio.wait_for(model.started.wait(), timeout=1)
        stopped = await asyncio.wait_for(
            receiver.inject(_message("stop", "/stop")),
            timeout=1,
        )
        assert stopped["kind"] == "session"
        assert stopped["result"]["status"] == "cancelled"
        assert (await service.get_session(accepted["result"]["session_id"]))["status"] == "cancelled"
    finally:
        await _close(service, channels, runtime)


async def test_stop_prevents_first_message_after_session_binding(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="must not run")])
    service = await _agent(tmp_path, model)
    registry = await _registry(tmp_path)
    channels = ChannelManager(registry.channelRegister)
    entered_submit = asyncio.Event()
    release_submit = asyncio.Event()
    stop_dispatched = asyncio.Event()
    agent = _AgentCommands(service)

    class PausedFirstSubmit:
        async def dispatch(self, command, *, valid=None):
            operation, _ = command.operation()
            if operation == "message":
                entered_submit.set()
                await release_submit.wait()
            elif operation == "stop":
                stop_dispatched.set()
            return await agent.dispatch(command, valid=valid)

        async def wait(self, turn_id):
            return await agent.wait(turn_id)

        async def wait_command(self, session_id, *, request_id=None, event_id=None):
            return await agent.wait_command(
                session_id, request_id=request_id, event_id=event_id,
            )

    await channels.configure_agent(
        PausedFirstSubmit(), tmp_path / "agents" / "channels.sqlite3",
    )
    await channels.start_agent([_config()])
    runtime = channels
    try:
        receiver = channels.receiver(runtime.configs["test"])
        message_task = asyncio.create_task(receiver.inject(_message("first", "start turn")))
        await asyncio.wait_for(entered_submit.wait(), timeout=2)
        queued_task = asyncio.create_task(receiver.inject(_message("queued", "must not start")))
        peer = runtime._peer(runtime.configs["test"], _message("first", "start turn"))
        bound_session = await runtime.bindings.current(peer)
        assert bound_session is not None

        stop_task = asyncio.create_task(receiver.inject(_message("stop-first", "/stop")))
        await asyncio.wait_for(stop_dispatched.wait(), timeout=2)
        assert not message_task.done()
        assert not stop_task.done()

        release_submit.set()
        accepted, stopped, queued = await asyncio.wait_for(
            asyncio.gather(message_task, stop_task, queued_task, return_exceptions=True),
            timeout=3,
        )

        assert accepted["kind"] == "error"
        assert accepted["error"]["code"] == "message_interrupted"
        assert stopped["kind"] == "session"
        assert stopped["result"]["status"] == "created"
        assert queued["kind"] == "error"
        assert queued["error"]["code"] == "message_interrupted"
        session = service.sessions[bound_session]
        assert session.status == "created"
        assert session.task is None
        assert model.seen == []
        assert not any(not task.done() for task in service._turns.values())
    finally:
        release_submit.set()
        await _close(service, channels, runtime)


async def test_bindings_restart_marks_accepted_undelivered_request_unknown(tmp_path):
    path = tmp_path / "channels.sqlite3"
    bindings = ChannelBindings(path)
    await bindings.start()
    peer = "peer-key"
    response = {"channel": "test", "kind": "turn", "result": {"turn_id": "turn-1"}}
    assert await bindings.claim(peer, "request-1", "digest") is None
    await bindings.complete(peer, "request-1", response)
    await bindings.close()

    restored = ChannelBindings(path)
    await restored.start()
    try:
        outcome = await restored.outcome(peer, "request-1")
        assert outcome["response"] == response
        assert outcome["delivery"]["status"] == "outcome_unknown"
        assert outcome["delivery"]["error"]["code"] == "delivery_interrupted"
    finally:
        await restored.close()


async def test_legacy_identity_migration_rejects_conflicting_session_or_receipt(tmp_path):
    bindings = ChannelBindings(tmp_path / "channels.sqlite3")
    await bindings.start()
    try:
        await bindings.bind("old", "session-a")
        await bindings.bind("current", "session-b")
        with pytest.raises(LogAgentError) as conflict:
            await bindings.migrate_peer("old", "current")
        assert conflict.value.code == "request_conflict"
        assert await bindings.current("current") == "session-b"

        await bindings.bind("current", "session-a")
        await bindings.claim("old", "message", "same-digest")
        await bindings.complete("old", "message", {"kind": "session", "result": "old"})
        await bindings.claim("current", "message", "same-digest")
        await bindings.complete("current", "message", {"kind": "session", "result": "current"})
        with pytest.raises(LogAgentError) as conflict:
            await bindings.migrate_peer("old", "current")
        assert conflict.value.code == "request_conflict"
        assert (await bindings.outcome("current", "message"))["response"]["result"] == "current"
    finally:
        await bindings.close()


async def test_restart_reconciles_durable_agent_operations_without_replaying(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="persisted reply")])
    service, manager, _ = await _start(tmp_path, model)
    config = _config()
    new_message = _message("crash-new", "/new")
    turn_message = _message("crash-turn", "hello")
    peer = manager._peer(config, new_message)
    created_id = manager._agent_request_id(config.id, peer, new_message.request_id)
    turn_id = manager._agent_request_id(config.id, peer, turn_message.request_id)
    try:
        for message, operation, operation_id in (
            (new_message, "new", created_id), (turn_message, "message", turn_id),
        ):
            await manager.bindings.claim(
                peer, message.request_id,
                manager._digest(message.model_dump(mode="json")),
                operation_id=operation_id, channel_id=config.id, operation=operation,
            )
            await manager.bindings.processing(peer, message.request_id)
            if operation == "new":
                created = await manager.agent_channel.dispatch(AgentCommand(
                    channel=config.id, request_id=operation_id, text="/new",
                ))
                session_id = created["result"]["session_id"]
            else:
                accepted = await manager.agent_channel.dispatch(AgentCommand(
                    channel=config.id, session=session_id, request_id=operation_id,
                    text="hello",
                ))
                await service.wait(accepted["result"]["turn_id"])
        assert len(model.seen) == 1
    finally:
        await _close(service, manager, manager)

    restored = await _agent(tmp_path, ScriptedModel(responses=[]))
    registry = await _registry(tmp_path)
    restarted = ChannelManager(registry.channelRegister)
    try:
        await restarted.configure_agent(
            _AgentCommands(restored), tmp_path / "agents" / "channels.sqlite3",
        )
        await restarted.start_agent([config])
        receiver = restarted.receiver(config)
        new_outcome = await restarted.outcome(config, new_message)
        turn_outcome = await restarted.outcome(config, turn_message)
        assert new_outcome["response"]["result"]["session_id"] == session_id
        assert new_outcome["status"] == "completed"
        assert turn_outcome["response"]["result"]["turn_id"] == accepted["result"]["turn_id"]
        assert turn_outcome["status"] == "completed"
        for outcome in (new_outcome, turn_outcome):
            assert outcome["delivery"]["status"] == "outcome_unknown"
        assert (await receiver.inject(new_message))["deduplicated"] is True
        assert (await receiver.inject(turn_message))["deduplicated"] is True
        assert await restarted.bindings.current(peer) == session_id
        assert len(restored.sessions) == 1
    finally:
        await _close(restored, restarted, restarted)


async def test_first_message_creation_crash_restores_binding_but_not_turn(tmp_path):
    service, manager, _ = await _start(tmp_path, ScriptedModel(responses=[]))
    config = _config()
    message = _message("first-crash", "never submitted")
    peer = manager._peer(config, message)
    request_id = manager._agent_request_id(config.id, peer, message.request_id)
    try:
        await manager.bindings.claim(
            peer, message.request_id, manager._digest(message.model_dump(mode="json")),
            operation_id=request_id, channel_id=config.id, operation="message",
        )
        await manager.bindings.processing(peer, message.request_id)
        created = await manager.agent_channel.dispatch(AgentCommand(
            channel=config.id, request_id=f"{request_id}:new", text="/new",
        ))
        session_id = created["result"]["session_id"]
    finally:
        await _close(service, manager, manager)

    restored = await _agent(tmp_path, ScriptedModel(responses=[]))
    registry = await _registry(tmp_path)
    restarted = ChannelManager(registry.channelRegister)
    try:
        await restarted.configure_agent(
            _AgentCommands(restored), tmp_path / "agents" / "channels.sqlite3",
        )
        await restarted.start_agent([config])
        assert await restarted.bindings.current(peer) == session_id
        outcome = await restarted.outcome(config, message)
        assert outcome["status"] == "outcome_unknown"
        assert outcome["response"] is None
        with pytest.raises(LogAgentError) as error:
            await restarted.receiver(config).inject(message)
        assert error.value.code == "request_outcome_unknown"
    finally:
        await _close(restored, restarted, restarted)


async def test_replayed_stop_does_not_cancel_a_new_queued_message(tmp_path):
    service, channels, runtime = await _start(
        tmp_path, ScriptedModel(responses=[AIMessage(content="new reply")]),
    )
    try:
        config = runtime.configs["test"]
        receiver = channels.receiver(config)
        await receiver.inject(_message("new", "/new"))
        stop = _message("old-stop", "/stop")
        await receiver.inject(stop)
        entered = asyncio.Event()

        class ObservedLock(asyncio.Lock):
            async def __aenter__(self):
                entered.set()
                return await super().__aenter__()

        lock = ObservedLock()
        runtime._conversation_processor._locks[runtime._peer(config, stop)] = lock
        await lock.acquire()
        try:
            pending = asyncio.create_task(receiver.inject(_message("later", "new message")))
            await asyncio.wait_for(entered.wait(), timeout=2)
            replayed = await receiver.inject(stop)
            assert replayed["deduplicated"] is True
        finally:
            lock.release()
        accepted = await asyncio.wait_for(pending, timeout=2)
        assert accepted["kind"] == "turn"
        await service.wait(accepted["result"]["turn_id"])
        await _settle_reply(runtime, receiver, "later")
    finally:
        await _close(service, channels, runtime)


async def test_reply_uses_the_inbound_address_and_one_way_send_uses_config_target(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="reply")])
    service, channels, runtime = await _start(tmp_path, model)
    try:
        config = runtime.configs["test"]
        receiver = channels.receiver(config)
        accepted = await receiver.inject(_message(
            "addressed", "hello", sender="user-7", target="group-9", kind="group",
        ))
        await service.wait(accepted["result"]["turn_id"])
        await _settle_reply(
            runtime, receiver, "addressed", sender="user-7", target="group-9", kind="group",
        )
        reply = receiver.outbox()[0]
        assert reply["address"] == {
            "kind": "group", "target": "group-9", "sender": "user-7",
            "message_id": "message-addressed",
        }

        one_way_config = _config(agent_enabled=False, target="workflow-output")
        with pytest.raises(LogAgentError) as no_agent_receiver:
            await channels.start_receiving(one_way_config, receiver.inject)
        assert no_agent_receiver.value.code == "channel_disabled"
        notification = Notification(session_id="workflow", output_id="result", text="report")
        receipt = await channels.send(one_way_config, notification)
        assert receipt.status == "success"
        assert receiver.handler is not None
        one_way_receiver = channels.receiver(one_way_config)
        assert one_way_receiver.handler is None
        assert one_way_receiver.outbox()[0]["address"] == {
            "kind": "test", "target": "workflow-output",
        }
        assert len(model.seen) == 1
    finally:
        await _close(service, channels, runtime)


async def test_disabled_channel_and_closed_runtime_reject_inbound(tmp_path):
    model = ScriptedModel(responses=[])
    service, channels, runtime = await _start(tmp_path, model, _config(enabled=False))
    try:
        with pytest.raises(LogAgentError) as not_started:
            channels.receiver(_config(enabled=False))
        assert not_started.value.code == "channel_unavailable"

        await runtime.configure([_config()])
        receiver = channels.receiver(runtime.configs["test"])
        await runtime.close()
        with pytest.raises(LogAgentError) as closed:
            await receiver.inject(_message("closed", "hello"))
        assert closed.value.code == "channel_disabled"
    finally:
        await channels.stop()
        await service.close()


class _WorkflowAI:
    def validate(self, config):
        return None

    async def execute(self, config, prompt, text, *, model, task_id, context,
                      system_prompt=None, user_prompt=""):
        return AnalysisResult(task_id=task_id, status="success", text="workflow report")


async def test_workflow_notification_uses_manager_and_test_channel_one_way_send(tmp_path):
    registry = PluginRegistry([MockCollector()], builtin_channels=[TestChannelType()])
    await registry.discover_plugins(
        SystemConfig(plugin_dir=str(tmp_path / "plugins"), data_dir=str(tmp_path))
    )
    channels = ChannelManager(registry.channelRegister)
    workflow = WorkflowRunner(
        CollectorManager(registry.collectorRegister),
        _WorkflowAI(),
        channels,
        database=tmp_path / "workflows.sqlite3",
    )
    snapshot = WorkflowSnapshot(
        workflow=WorkflowDefinition(
            id="duplex-test",
            name="One-way workflow result",
            sources=["source"],
            analyses=[AnalysisTask(id="analysis", ai="ai", model="offline")],
            channels=["test"],
        ),
        sources={"source": SourceConfig(id="source", collector="mock")},
        ai={"ai": AIConfig(id="ai", provider="offline", models={"offline": {}})},
        channels={
            "test": ChannelConfig(
                id="test",
                channel="test",
                options={"target": "workflow-output"},
                agent_enabled=False,
            )
        },
        created_at=datetime.now(UTC),
    )
    try:
        await workflow.validate(snapshot)
        await workflow.trigger(snapshot, session_id="workflow-run")
        result = await workflow.wait("workflow-run")

        assert result.status == "completed"
        assert [receipt.status for receipt in result.deliveries] == ["success"]
        receiver = channels.receiver(snapshot.channels["test"])
        assert receiver.handler is None
        assert receiver.outbox()[0]["address"] == {
            "kind": "test", "target": "workflow-output",
        }
        assert receiver.outbox()[0]["notification"]["text"] == "workflow report"
    finally:
        await workflow.shutdown()
        await channels.stop()


async def test_runtime_configure_toggles_agent_receiving_without_replacing_send(tmp_path):
    model = ScriptedModel(responses=[])
    service, channels, runtime = await _start(tmp_path, model)
    try:
        config = runtime.configs["test"]
        receiver = channels.receiver(config)
        assert receiver.handler is not None

        await runtime.configure([config.model_copy(update={"agent_enabled": False})])
        assert runtime.configs == {}
        assert receiver.handler is None
        with pytest.raises(LogAgentError) as disabled:
            await receiver.inject(_message("disabled", "hello"))
        assert disabled.value.code == "channel_disabled"

        await runtime.configure([config])
        assert channels.receiver(config) is receiver
        assert receiver.handler is not None

        await runtime.configure([config.model_copy(update={"enabled": False})])
        assert runtime.configs == {}
        assert receiver.handler is None
    finally:
        await _close(service, channels, runtime)


async def test_failed_receiver_stop_keeps_runtime_configuration_for_retry(tmp_path):
    model = ScriptedModel(responses=[])
    service, channels, runtime = await _start(tmp_path, model)
    try:
        config = runtime.configs["test"]
        receiver = channels.receiver(config)
        original_stop = channels.stop_receiving
        fail_once = True

        async def stop_once_then_succeed(candidate):
            nonlocal fail_once
            if fail_once:
                fail_once = False
                raise RuntimeError("receiver did not stop")
            await original_stop(candidate)

        channels.stop_receiving = stop_once_then_succeed
        changed = config.model_copy(update={"agent_enabled": False})
        with pytest.raises(RuntimeError, match="receiver did not stop"):
            await runtime.configure([changed])
        assert runtime.configs["test"] == config
        assert receiver.handler is not None

        await runtime.configure([changed])
        assert runtime.configs == {}
        assert receiver.handler is None
    finally:
        await _close(service, channels, runtime)
