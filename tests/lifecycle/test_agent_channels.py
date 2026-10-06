"""Lifecycle and HTTP integration coverage for the builtin Agent test channel."""

import asyncio
import json

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import Field

from logagent.agent.commands import AgentCommand
from logagent.channel import builtin_channels
from logagent.channel.bindings import ChannelBindings
from logagent.channel.conversation import ChannelAddress, InboundMessage
from logagent.channel.manager import ChannelManager
from logagent.config import PluginRegistry, ResourceStore
from logagent.errors import LogAgentError
from logagent.interaction.app import create_app
from logagent.lifecycle import ApplicationLifecycle
from logagent.models import ChannelConfig, Notification, SystemConfig
from tests.agent.helpers import ScriptedModel
from tests.agent.test_admission import GatedModel
from tests.fixtures.plugin_helpers import install_test_channel_plugin


async def _seed_channel(config, *, agent_enabled=True):
    install_test_channel_plugin(config.plugin_dir)
    registry = PluginRegistry(
        [],
        builtin_channels=builtin_channels(),
    )
    await registry.discover_plugins(config)
    resources = ResourceStore(
        f"{config.data_dir}/resources.json",
        collector_register=registry.collectorRegister,
        channel_register=registry.channelRegister,
        data_dir=config.data_dir,
    )
    return resources.save(
        "channels",
        ChannelConfig(
            id="test",
            channel="test",
            options={"target": "lifecycle-output"},
            agent_enabled=agent_enabled,
        ),
    )


async def _wait_for_channel_sync(services):
    task = services.channels._sync_task
    assert task is not None
    await asyncio.wait_for(asyncio.shield(task), timeout=5)


async def _wait_for_delivery(client, message):
    for _ in range(200):
        outcome = await client.post("/api/channels/test/test/outcome", json=message)
        assert outcome.status_code == 200
        result = outcome.json()
        if result["delivery"] is not None:
            return result
        await asyncio.sleep(0.01)
    pytest.fail("Agent channel reply was not delivered")


async def _inject_result(services, config, receiver, message):
    accepted = await receiver.inject(message)
    assert accepted["status"] in {"accepted", "duplicate"}
    async with asyncio.timeout(5):
        while True:
            outcome = await services.channels.outcome(config, message)
            if outcome["response"] is not None:
                return outcome["response"]
            await asyncio.sleep(0.005)


async def _bind_channel(services, ident="test"):
    created = await services.channels.dispatch_web(AgentCommand(
        channel="web", action="new", request_id=f"bind-{ident}",
    ))
    session = created["result"]["session_id"]
    await services.channels.bind_conversation(ident, session)
    return session


async def test_lifecycle_resources_reload_plugin_reload_and_test_channel_http(tmp_path):
    config = SystemConfig(
        data_dir=str(tmp_path / "data"),
        plugin_dir=str(tmp_path / "plugins"),
    )
    await _seed_channel(config)
    lifecycle = ApplicationLifecycle(config, channel_factories={})
    app = create_app(lifecycle)
    async with app.router.lifespan_context(app):
        services = app.state.services
        model = ScriptedModel(responses=[AIMessage(content="HTTP channel reply")])
        services.agent.model_provider = lambda _: model
        active_config = services.resources.get("channels", "test")
        original_receiver = services.channels.receiver(active_config)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            created = await client.post("/api/channels/web/commands", json={
                "action": "new", "request_id": "bind-http",
            })
            assert created.status_code == 202
            session = created.json()["result"]["session_id"]
            initial = await client.get("/api/channels/test/conversation")
            assert initial.json() == {"session_id": None}
            bound = await client.put("/api/channels/test/conversation", json={
                "session_id": session,
            })
            assert bound.status_code == 200
            assert bound.json() == {"session_id": session}
            invalid = await client.put("/api/channels/test/conversation", json={
                "session_id": "missing-session",
            })
            assert invalid.status_code == 409
            assert invalid.json()["error"]["code"] == "session_not_found"
            assert (await client.get("/api/channels/test/conversation")).json() == {
                "session_id": session,
            }
            message = {
                "request_id": "http-request-1",
                "text": "hello from HTTP",
                "address": {
                    "kind": "test",
                    "target": "http-peer",
                    "sender": "http-user",
                    "message_id": "http-message-1",
                },
            }
            injected = await client.post("/api/channels/test/test/messages", json=message)
            assert injected.status_code == 202
            accepted = injected.json()
            assert accepted == {"status": "accepted"}
            outcome = await _wait_for_delivery(client, message)
            assert outcome["response"]["kind"] == "turn"
            assert outcome["delivery"]["status"] == "success"
            assert outcome["response"]["result"]["session_id"] == session
            events = await client.get(f"/api/channels/web/sessions/{session}/events")
            assert events.status_code == 200
            assert "HTTP channel reply" in events.text

            outbox = await client.get("/api/channels/test/test/messages")
            assert outbox.status_code == 200
            assert outbox.json()[0]["address"] == message["address"]
            assert outbox.json()[0]["notification"]["text"] == "HTTP channel reply"

            disabled_config = active_config.model_copy(update={"agent_enabled": False})
            services.resources.save("channels", disabled_config, mode="replace")
            await _wait_for_channel_sync(services)
            assert original_receiver.handler is None
            rejected = await client.post("/api/channels/test/test/messages", json={
                **message,
                "request_id": "http-request-disabled",
                "address": {**message["address"], "message_id": "http-message-disabled"},
            })
            assert rejected.json()["error"]["code"] == "channel_disabled"

            services.resources.save("channels", active_config, mode="replace")
            await _wait_for_channel_sync(services)
            assert services.channels.receiver(active_config) is original_receiver
            assert original_receiver.handler is not None

            await lifecycle.reload("plugins")
            reloaded_receiver = services.channels.receiver(active_config)
            assert reloaded_receiver is not original_receiver
            assert original_receiver.started is False
            assert reloaded_receiver.handler is not None
            assert reloaded_receiver.started is True
            previous_outbox_size = len(reloaded_receiver.outbox())

            receipt = await services.channels.send(
                active_config,
                Notification(
                    session_id="workflow-run",
                    output_id="workflow-result",
                    text="one-way workflow output",
                ),
            )
            assert receipt.status == "success"
            assert reloaded_receiver.handler is not None
            assert reloaded_receiver.outbox()[-1]["address"] == {
                "kind": "test",
                "target": "lifecycle-output",
            }
            assert reloaded_receiver.outbox()[-1]["notification"]["text"] \
                == "one-way workflow output"
            assert len(reloaded_receiver.outbox()) == previous_outbox_size + 1

    assert reloaded_receiver.handler is None
    assert reloaded_receiver.started is False
    assert rejected.status_code == 409


async def test_plugin_reload_conflicts_while_channel_reply_is_in_flight(tmp_path, monkeypatch):
    config = SystemConfig(data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"))
    channel = await _seed_channel(config)
    lifecycle = ApplicationLifecycle(config, channel_factories={})
    services = await lifecycle.start()
    await _bind_channel(services)
    services.agent.model_provider = lambda _: ScriptedModel(
        responses=[AIMessage(content="completed before delivery")],
    )
    receiver = services.channels.receiver(channel)
    started, release = asyncio.Event(), asyncio.Event()
    original_reply = receiver.reply

    async def delayed_reply(notification, *, address, options):
        started.set()
        await release.wait()
        await original_reply(notification, address=address, options=options)

    monkeypatch.setattr(receiver, "reply", delayed_reply)
    message = InboundMessage(
        request_id="reply-in-flight", text="hello",
        address=ChannelAddress(
            kind="test", target="room", sender="alice", message_id="reply-in-flight",
        ),
    )
    try:
        accepted = await _inject_result(services, channel, receiver, message)
        await services.agent.wait(accepted["result"]["turn_id"])
        await asyncio.wait_for(started.wait(), 2)
        assert services.channels.active_operations > 0
        with pytest.raises(LogAgentError) as error:
            await lifecycle.reload("plugins")
        assert error.value.code == "plugin_reload_conflict"
        assert receiver.started is True
        release.set()
        async with asyncio.timeout(2):
            while (await services.channels.outcome(channel, message))["delivery"] is None:  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        await lifecycle.reload("plugins")
    finally:
        release.set()
        await lifecycle.shutdown()


async def test_web_commands_and_sse_use_the_lifecycle_channel_manager(tmp_path):
    config = SystemConfig(
        data_dir=str(tmp_path / "data"),
        plugin_dir=str(tmp_path / "plugins"),
    )
    lifecycle = ApplicationLifecycle(config, channel_factories={})
    app = create_app(lifecycle)
    async with app.router.lifespan_context(app):
        services = app.state.services
        model = ScriptedModel(responses=[AIMessage(content="reply through WebChannel")])
        services.agent.model_provider = lambda _: model
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            created = await client.post("/api/channels/web/commands", json={
                "channel": "web",
                "request_id": "web-new",
                "action": "new",
            })
            assert created.status_code == 202
            session_id = created.json()["result"]["session_id"]

            submitted = await client.post("/api/channels/web/commands", json={
                "channel": "web",
                "session": session_id,
                "request_id": "web-message",
                "action": "message",
                "text": "hello from the web channel",
            })
            assert submitted.status_code == 202
            assert submitted.json()["kind"] == "turn"
            await services.agent.wait(submitted.json()["result"]["turn_id"])

            stream = await client.get(
                f"/api/channels/web/sessions/{session_id}/events",
                params={"after": 0},
            )
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            events = [
                json.loads(line[6:])
                for line in stream.text.splitlines()
                if line.startswith("data: ")
            ]
            assert events
            assert [event["id"] for event in events] == sorted(
                event["id"] for event in events
            )
            assert events[-1]["type"] == "turn.completed"
            assert events[-1]["text"] == "reply through WebChannel"
            assert "hello from the web channel" in str(model.seen[-1])


async def test_receiver_restart_failure_keeps_reload_admission_closed(tmp_path, monkeypatch):
    config = SystemConfig(data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"))
    await _seed_channel(config)
    lifecycle = ApplicationLifecycle(config, channel_factories={})
    services = await lifecycle.start()
    start_receiving = services.channels.start_receiving

    async def fail_receiving(config, handler):
        raise LogAgentError("receiver_restart_failed", "receiver restart failed")

    try:
        monkeypatch.setattr(services.channels, "start_receiving", fail_receiving)
        with pytest.raises(LogAgentError, match="receiver restart failed"):
            await lifecycle.reload("plugins")
        assert services.agent.accepting is False
        assert services.workflow.coordinator.accepting is False
        assert services.channels.configs == {}

        monkeypatch.setattr(services.channels, "start_receiving", start_receiving)
        await lifecycle.reload("plugins")
        assert services.agent.accepting is True
        assert services.workflow.coordinator.accepting is True
        assert services.channels.receiver(services.resources.get("channels", "test")).handler is not None
    finally:
        await lifecycle.shutdown()


async def test_manager_stop_interrupts_queued_request_and_retains_new_input(tmp_path):
    config = SystemConfig(data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"))
    await _seed_channel(config)
    lifecycle = ApplicationLifecycle(config, channel_factories={})
    services = await lifecycle.start()
    await _bind_channel(services)
    model = GatedModel(responses=[AIMessage(content="reply after stop")])
    services.agent.model_provider = lambda _: model
    channel = services.resources.get("channels", "test")
    receiver = services.channels.receiver(channel)

    def inbound(request_id, text):
        return InboundMessage(
            request_id=request_id, text=text,
            address=ChannelAddress(
                kind="test", target="stop-room", sender="alice", message_id=request_id,
            ),
        )

    try:
        first = await _inject_result(services, channel, receiver, inbound("running", "A"))
        await asyncio.wait_for(model.entered.wait(), 2)
        services.channels._input_queue.capacity = 1
        waiting = asyncio.create_task(
            _inject_result(services, channel, receiver, inbound("waiting", "B"))
        )
        async with asyncio.timeout(2):
            while services.channels._input_queue.size(("channel", channel.id, "normal")) != 1:  # noqa: ASYNC110
                await asyncio.sleep(0)

        with pytest.raises(LogAgentError) as full:
            await receiver.inject(inbound("overflow", "would overflow"))
        assert full.value.code == "channel_queue_full"

        stopped = await asyncio.wait_for(
            _inject_result(services, channel, receiver, inbound("stop", "/stop")), 2,
        )
        rejected = await asyncio.wait_for(waiting, 2)
        assert stopped["result"]["status"] == "cancelled"
        assert rejected["error"]["code"] == "message_interrupted"
        outcome = await services.channels.outcome(channel, inbound("waiting", "B"))
        assert outcome["status"] == "interrupted"
        assert outcome["delivery"]["status"] == "not_started"
        assert first["result"]["session_id"] == stopped["result"]["session_id"]
        assert await receiver.inject(inbound("stop", "/stop")) == {"status": "duplicate"}

        model.release.set()
        subsequent = await _inject_result(services, channel, receiver, inbound("later", "C"))
        await services.agent.wait(subsequent["result"]["turn_id"])
        assert subsequent["kind"] == "turn"
    finally:
        model.release.set()
        await lifecycle.shutdown()


async def test_verified_legacy_identity_maps_old_request_without_reexecution(tmp_path):
    config = SystemConfig(data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"))
    channel = await _seed_channel(config)
    message = InboundMessage(
        request_id="legacy-new", text="/new",
        address=ChannelAddress(
            kind="test", target="legacy-room", sender="alice", message_id="legacy-id",
        ),
    )
    legacy_peer = ChannelManager._digest([
        channel.id, channel.channel, channel.options, message.address.peer,
    ])
    bindings = ChannelBindings(tmp_path / "data" / "agents" / "channels.sqlite3")
    await bindings.start()
    await bindings.claim(legacy_peer, message.request_id, ChannelManager._digest(
        message.model_dump(mode="json")
    ))
    await bindings.complete(legacy_peer, message.request_id, {
        "channel": "test", "kind": "session", "result": {"session_id": "legacy-session"},
    })
    await bindings.close()

    lifecycle = ApplicationLifecycle(config, channel_factories={})
    services = await lifecycle.start()
    try:
        received = await services.channels.receiver(channel).inject(message)
        assert received == {"status": "duplicate"}
        outcome = await services.channels.outcome(channel, message)
        assert outcome["response"]["result"]["session_id"] == "legacy-session"
        assert outcome["status"] == "completed"
        new_peer = services.channels._peer(channel, message)
        assert await services.channels.bindings.outcome(new_peer, message.request_id)
    finally:
        await lifecycle.shutdown()


def test_qq_conversation_identity_depends_on_app_id_not_send_target_or_secret():
    message = InboundMessage(
        request_id="qq-1", text="hello",
        address=ChannelAddress(kind="group", target="group-1", sender="member-1", message_id="qq-1"),
    )
    first = ChannelConfig(id="qq", channel="qq", options={
        "app_id": "account-a", "client_secret": "old", "target_id": "one",
    })
    rotated = first.model_copy(update={"options": {
        "app_id": "account-a", "client_secret": "new", "target_id": "two",
    }})
    other = first.model_copy(update={"options": {
        "app_id": "account-b", "client_secret": "old", "target_id": "one",
    }})
    assert ChannelManager._peer(first, message) == ChannelManager._peer(rotated, message)
    assert ChannelManager._peer(first, message) != ChannelManager._peer(other, message)


async def test_web_receipt_deduplication_and_http_disconnect_keep_manager_work(tmp_path):
    config = SystemConfig(data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"))
    lifecycle = ApplicationLifecycle(config, channel_factories={})
    app = create_app(lifecycle)
    async with app.router.lifespan_context(app):
        services = app.state.services
        model = GatedModel(responses=[AIMessage(content="first"), AIMessage(content="second")])
        services.agent.model_provider = lambda _: model
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            created = await client.post("/api/channels/web/commands", json={
                "action": "new", "request_id": "create-web",
            })
            assert created.status_code == 202
            session = created.json()["result"]["session_id"]
            first = await client.post("/api/channels/web/commands", json={
                "session": session, "action": "message", "request_id": "first", "text": "A",
            })
            assert first.status_code == 202
            await model.entered.wait()

            payload = {"session": session, "action": "message", "request_id": "queued", "text": "B"}
            disconnected = asyncio.create_task(client.post("/api/channels/web/commands", json=payload))
            peer = f"web:session:{session}"
            async with asyncio.timeout(2):
                while services.channels._input_queue.size(("web", peer, "normal")) != 1:  # noqa: ASYNC110
                    await asyncio.sleep(0)
            disconnected.cancel()
            await asyncio.gather(disconnected, return_exceptions=True)
            model.release.set()
            accepted = await client.post("/api/channels/web/commands", json=payload)
            assert accepted.status_code == 202
            assert accepted.json()["deduplicated"] is True
            assert accepted.json()["result"]["turn_id"] != first.json()["result"]["turn_id"]
            await services.agent.wait(accepted.json()["result"]["turn_id"])
            receipt = await client.get(
                "/api/channels/web/requests/queued", params={"session": session},
            )
            assert receipt.status_code == 200
            assert receipt.json()["status"] == "completed"
            conflict = await client.post("/api/channels/web/commands", json={
                **payload, "text": "different",
            })
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "request_conflict"


async def test_manager_session_switch_keeps_prior_input_in_the_old_session(tmp_path):
    config = SystemConfig(data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"))
    await _seed_channel(config)
    lifecycle = ApplicationLifecycle(config, channel_factories={})
    services = await lifecycle.start()
    await _bind_channel(services)
    model = GatedModel(responses=[
        AIMessage(content="A"), AIMessage(content="B"), AIMessage(content="C"),
    ])
    services.agent.model_provider = lambda _: model
    channel = services.resources.get("channels", "test")
    receiver = services.channels.receiver(channel)

    def inbound(request_id, text):
        return InboundMessage(
            request_id=request_id, text=text,
            address=ChannelAddress(
                kind="test", target="switch-room", sender="alice", message_id=request_id,
            ),
        )

    async def queued(key, count):
        async with asyncio.timeout(2):
            while services.channels._input_queue.size(key) != count:  # noqa: ASYNC110
                await asyncio.sleep(0)

    try:
        first = await _inject_result(services, channel, receiver, inbound("A", "first"))
        await model.entered.wait()
        b_task = asyncio.create_task(
            _inject_result(services, channel, receiver, inbound("B", "second"))
        )
        await queued(("channel", channel.id, "normal"), 1)
        new_task = asyncio.create_task(
            _inject_result(services, channel, receiver, inbound("new", "/new"))
        )
        await queued(("channel", channel.id, "command"), 1)
        c_task = asyncio.create_task(
            _inject_result(services, channel, receiver, inbound("C", "third"))
        )
        await queued(("channel", channel.id, "normal"), 2)
        model.release.set()
        second, switched, third = await asyncio.wait_for(
            asyncio.gather(b_task, new_task, c_task), 5,
        )
        assert second["result"]["session_id"] == first["result"]["session_id"]
        assert switched["result"]["session_id"] != first["result"]["session_id"]
        assert third["error"]["code"] == "channel_binding_changed"
        fresh = await _inject_result(services, channel, receiver, inbound("D", "fresh"))
        assert fresh["result"]["session_id"] == switched["result"]["session_id"]
        await services.agent.wait(fresh["result"]["turn_id"])
    finally:
        model.release.set()
        await lifecycle.shutdown()


async def test_web_and_test_channel_serialize_turns_of_the_same_agent_session(tmp_path):
    config = SystemConfig(data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"))
    await _seed_channel(config)
    lifecycle = ApplicationLifecycle(config, channel_factories={})
    app = create_app(lifecycle)
    async with app.router.lifespan_context(app):
        services = app.state.services
        await _bind_channel(services)
        model = GatedModel(responses=[AIMessage(content="test"), AIMessage(content="web")])
        services.agent.model_provider = lambda _: model
        channel = services.resources.get("channels", "test")
        receiver = services.channels.receiver(channel)
        first_message = InboundMessage(
            request_id="test-first", text="first",
            address=ChannelAddress(
                kind="test", target="shared", sender="alice", message_id="test-first",
            ),
        )
        first = await _inject_result(services, channel, receiver, first_message)
        await model.entered.wait()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            session = first["result"]["session_id"]
            waiting = asyncio.create_task(client.post("/api/channels/web/commands", json={
                "session": session, "action": "message", "request_id": "web-second", "text": "second",
            }))
            try:
                async with asyncio.timeout(2):
                    while (await client.get(  # noqa: ASYNC110
                        "/api/channels/web/requests/web-second", params={"session": session},
                    )).status_code == 404:
                        await asyncio.sleep(0)
                assert not waiting.done()
                model.release.set()
                second = await asyncio.wait_for(waiting, 5)
                assert second.status_code == 202
                assert second.json()["result"]["session_id"] == session
                assert second.json()["result"]["turn_id"] != first["result"]["turn_id"]
                await services.agent.wait(second.json()["result"]["turn_id"])
                assert len(model.seen) == 2
            finally:
                model.release.set()


async def test_web_stop_interrupts_waiting_admission_to_shared_session(tmp_path):
    config = SystemConfig(data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"))
    await _seed_channel(config)
    lifecycle = ApplicationLifecycle(config, channel_factories={})
    services = await lifecycle.start()
    await _bind_channel(services)
    model = GatedModel(responses=[AIMessage(content="first"), AIMessage(content="obsolete")])
    services.agent.model_provider = lambda _: model
    receiver = services.channels.receiver(services.resources.get("channels", "test"))
    try:
        channel = services.resources.get("channels", "test")
        first_message = InboundMessage(
            request_id="shared-first", text="A",
            address=ChannelAddress(
                kind="test", target="shared", sender="alice", message_id="shared-first",
            ),
        )
        first = await _inject_result(services, channel, receiver, first_message)
        await asyncio.wait_for(model.entered.wait(), 2)
        session = first["result"]["session_id"]
        web = services.channels.web_channel
        waiting = asyncio.create_task(web.dispatch(AgentCommand(
            channel="web", action="message", session=session,
            request_id="web-waiting", text="B",
        )))
        peer = f"web:session:{session}"
        async with asyncio.timeout(2):
            while True:  # noqa: ASYNC110
                try:
                    pending = await services.channels.bindings.outcome(peer, "web-waiting")
                except LogAgentError as exc:
                    if exc.code != "request_not_found":
                        raise
                else:
                    if pending["status"] == "processing":
                        break
                await asyncio.sleep(0)
        stopped = await web.dispatch(AgentCommand(
            channel="web", action="stop", session=session, request_id="web-stop",
        ))
        assert stopped["result"]["status"] == "cancelled"
        with pytest.raises(LogAgentError) as error:
            await asyncio.wait_for(waiting, 2)
        assert error.value.code == "message_interrupted"
        events = await services.agent.events(session)
        assert not any(event.get("request_id") == services.channels._agent_request_id(
            "web", peer, "web-waiting",
        ) and event["type"] == "request.accepted" for event in events)
        assert (await services.channels.web_outcome("web-waiting", session=session))[
            "status"
        ] == "interrupted"
    finally:
        model.release.set()
        await lifecycle.shutdown()


async def test_lifecycle_shutdown_drains_cancelled_agent_reply_before_channel_and_database_close(
    tmp_path,
):
    config = SystemConfig(
        data_dir=str(tmp_path / "data"),
        plugin_dir=str(tmp_path / "plugins"),
    )
    await _seed_channel(config)
    lifecycle = ApplicationLifecycle(config, channel_factories={})
    services = await lifecycle.start()
    await _bind_channel(services)

    class WaitingModel(ScriptedModel):
        started: asyncio.Event = Field(default_factory=asyncio.Event)

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.seen.append(list(messages))
            self.started.set()
            await asyncio.Future()

    model = WaitingModel(responses=[])
    services.agent.model_provider = lambda _: model
    channel_config = services.resources.get("channels", "test")
    receiver = services.channels.receiver(channel_config)
    inbound = InboundMessage(
        request_id="shutdown-request",
        text="wait until shutdown",
        address=ChannelAddress(
            kind="test",
            target="shutdown-peer",
            sender="shutdown-user",
            message_id="shutdown-message",
        ),
    )
    accepted = await _inject_result(services, channel_config, receiver, inbound)
    await asyncio.wait_for(model.started.wait(), timeout=5)

    order = []
    original_pause = services.agent.pause_admission
    original_suspend = services.channels.suspend
    original_agent_close = services.agent.close
    original_runtime_close = services.channels.close
    original_receiver_stop = receiver.stop

    async def pause_agent():
        result = await original_pause()
        order.append("agent_paused")
        return result

    async def suspend_inbound():
        result = await original_suspend()
        order.append("inbound_suspended")
        return result

    async def close_agent():
        result = await original_agent_close()
        order.append("agent_closed")
        return result

    async def close_runtime():
        result = await original_runtime_close()
        order.append("runtime_drained_and_database_closed")
        return result

    async def stop_receiver():
        result = await original_receiver_stop()
        order.append("channel_stopped")
        return result

    services.agent.pause_admission = pause_agent
    services.channels.suspend = suspend_inbound
    services.agent.close = close_agent
    services.channels.close = close_runtime
    receiver.stop = stop_receiver
    try:
        await asyncio.wait_for(lifecycle.shutdown(), timeout=15)

        assert services.agent.accepting is False
        assert services.channels.configs == {}
        assert receiver.handler is None
        assert accepted["result"]["session_id"] in services.agent.sessions
        assert not any(not task.done() for task in services.agent.turns.tasks.values())
        assert order.index("agent_paused") < order.index("inbound_suspended")
        assert order.index("inbound_suspended") < order.index("agent_closed")
        assert order.index("agent_closed") < order.index("runtime_drained_and_database_closed")
        assert order.index("runtime_drained_and_database_closed") < order.index("channel_stopped")
        assert services.channels.bindings._db is None
        assert receiver.started is False
        assert receiver.outbox()[-1]["notification"]["text"] == "本轮已停止。"
    finally:
        await lifecycle.shutdown()


async def test_conversation_http_unbind_resume_and_one_way_rejection(tmp_path):
    config = SystemConfig(data_dir=str(tmp_path / "data"), plugin_dir=str(tmp_path / "plugins"))
    await _seed_channel(config)
    lifecycle = ApplicationLifecycle(config, channel_factories={})
    app = create_app(lifecycle)
    async with app.router.lifespan_context(app):
        services = app.state.services
        services.resources.save("channels", ChannelConfig(
            id="file-only", channel="file", options={"path": "output.log"},
        ))
        await _wait_for_channel_sync(services)
        first = await _bind_channel(services)
        created = await services.channels.dispatch_web(AgentCommand(
            channel="web", action="new", request_id="other-conversation",
        ))
        target = created["result"]["session_id"]
        channel = services.resources.get("channels", "test")
        receiver = services.channels.receiver(channel)

        def inbound(ident, text):
            return InboundMessage(request_id=ident, text=text, address=ChannelAddress(
                kind="test", target="room", sender="alice", message_id=ident,
            ))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            simplex = await client.put("/api/channels/file-only/conversation", json={
                "session_id": first,
            })
            assert simplex.status_code == 422
            assert simplex.json()["error"]["code"] == "channel_not_conversation"
            assert (await client.get("/api/channels/file-only/conversation")).status_code == 422
            malformed = await client.put("/api/channels/test/conversation", json={})
            assert malformed.status_code == 422
            unbound = await client.put("/api/channels/test/conversation", json={"session_id": None})
            assert unbound.status_code == 200
            assert unbound.json() == {"session_id": None}
            rejected = await _inject_result(services, channel, receiver, inbound("unbound", "hello"))
            assert rejected["error"]["code"] == "channel_unbound"
            resumed = await _inject_result(
                services, channel, receiver, inbound("resume", f"/resume {target}"),
            )
            assert resumed["result"]["session_id"] == target
            current = await client.get("/api/channels/test/conversation")
            assert current.json() == {"session_id": target}
            missing = await _inject_result(
                services, channel, receiver, inbound("missing", "/resume missing-session"),
            )
            assert missing["error"]["code"] == "session_not_found"
            assert (await client.get("/api/channels/test/conversation")).json() == {
                "session_id": target,
            }
