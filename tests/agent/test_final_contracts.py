import asyncio
import json

from langchain_core.messages import AIMessage

from tests.agent.helpers import ScriptedModel
from workflowweave.agent.config import AgentConfig
from workflowweave.agent.tools.builtin import mcp, read
from workflowweave.interaction.fastapi.agent import create_agent_service


async def test_graph_uses_gateway_execution_and_persists_bounded_artifact(tmp_path):
    calls = []
    entered = asyncio.Event()

    class Gateway:
        def execution(self, arguments):
            return "exclusive"

        async def invoke(self, arguments, context):
            calls.append(context.scheduler.status.copy())
            entered.set()
            return {"status": "success", "text": "result " * 4000}

    models = [ScriptedModel(responses=[AIMessage(content="", tool_calls=[{
        "id": "collector-1", "name": "mcp", "args": {"action": "call", "server": "logs", "tool": "read"},
    }]), AIMessage(content="done")])]
    gateway = Gateway()
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime",
                           config=AgentConfig(preview_tokens=200),
                           model_provider=lambda _: models[0], declarations=[mcp.plugin, read.plugin])
    # The gateway is injected directly for this isolated graph integration.
    original = service.resource_provider.capture
    from dataclasses import replace
    gateway.catalog = lambda *args, **kwargs: asyncio.sleep(0)
    service.resource_provider.capture = lambda session: replace(original(session), gateway=gateway)
    try:
        sid = (await service.create_session())["session_id"]
        async with service.scheduler.acquire("read"):
            accepted = await service.submit(sid, "collect", request_id="r1")
            await asyncio.sleep(0.05)
            assert not entered.is_set()
        await service.wait(accepted["turn_id"])
        assert len(calls) == 1 and calls[0]["writing"] == 1 and calls[0]["reading"] == 0
        events = await service.events(sid)
        tool_events = [event for event in events if event["type"].startswith("tool.")]
        assert [event["type"] for event in tool_events] == ["tool.queued", "tool.started", "tool.completed"]
        assert all(event["tool_call_id"] == "collector-1" for event in tool_events)
        assert all(event["turn_id"] == accepted["turn_id"] for event in tool_events)
        result = tool_events[-1]["result"]
        assert result["truncated"] is True and len(result["preview"]) < 28_000
        full = json.loads((service.runtime / result["artifact_path"]).read_text())
        assert full["text"] == "result " * 4000
    finally:
        await service.close()


async def test_append_enters_same_turn_only_after_complete_tool_group(tmp_path):
    from workflowweave.agent.tools.declaration import ToolDeclaration, schema
    started = asyncio.Event()
    release = asyncio.Event()

    async def invoke(arguments, context):
        started.set()
        await release.wait()
        return {"status": "success", "text": "receipt"}

    model = ScriptedModel(responses=[AIMessage(content="", tool_calls=[{
        "id": "call-1", "name": "held", "args": {},
    }]), AIMessage(content="answer to appended input")])
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model,
                           declarations=[ToolDeclaration("held", "held", schema({}), "read", invoke)])
    try:
        sid = (await service.create_session())["session_id"]
        first = await service.submit(sid, "original", request_id="first")
        await asyncio.wait_for(started.wait(), 1)
        queued = await service.append(sid, "new information", request_id="append")
        assert queued["turn_id"] == first["turn_id"]
        assert len(model.seen) == 1
        release.set()
        await service.wait(first["turn_id"])
        sequence = [message.type for message in model.seen[-1]]
        assert sequence[-3:] == ["ai", "tool", "human"]
        assert model.seen[-1][-1].content == "new information"
        events = await service.events(sid)
        assert sum(event["type"] == "turn.started" for event in events) == 1
        assert next(event["id"] for event in events if event["type"] == "tool.completed") < next(
            event["id"] for event in events if event["type"] == "message.user" and event["text"] == "new information")
    finally:
        await service.close()


async def test_stop_discards_queued_commands_without_starting_another_model(tmp_path):
    from tests.agent.test_admission import GatedModel
    model = GatedModel(responses=[AIMessage(content="never")])
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model)
    try:
        sid = (await service.create_session())["session_id"]
        await service.submit(sid, "original", request_id="first")
        await asyncio.wait_for(model.entered.wait(), 1)
        await service.append(sid, "queued", request_id="append")
        await service.compact(sid)
        await service.cancel(sid)
        events = await service.events(sid)
        assert len([event for event in events if event["type"] == "command.cancelled"]) == 2
        assert not any(event["type"] == "context.compacted" for event in events)
        assert not any(event["type"] == "message.user" and event["text"] == "queued" for event in events)
        assert not service.turns.current(sid).pending_appends
    finally:
        await service.close()


async def test_idle_manual_compact_uses_official_summary_and_keeps_history(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="answer " * 100), AIMessage(content="summary")])
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model,
                           config=AgentConfig(trigger_tokens=180000, keep_tokens=10))
    try:
        sid = (await service.create_session())["session_id"]
        turn = await service.submit(sid, "original fact " * 100, request_id="first")
        await service.wait(turn["turn_id"])
        before = await service.events(sid)
        accepted = await service.compact(sid)
        await service.wait(accepted["turn_id"])
        events = await service.events(sid)
        summary = next(event for event in events if event["type"] == "context.compacted")
        assert "summary" in summary["summary"] and summary["removed_message_ids"]
        assert events[:len(before)] == before
        assert (service.runtime / summary["artifact_path"]).is_file()
        assert len(model.seen) == 2
    finally:
        await service.close()


async def test_fork_from_old_turn_and_edited_message_never_inherits_future(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="first answer"), AIMessage(content="future answer"),
                                    AIMessage(content="branch answer"), AIMessage(content="edited answer")])
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model)
    try:
        sid = (await service.create_session())["session_id"]
        first = await service.submit(sid, "first question", request_id="first")
        await service.wait(first["turn_id"])
        second = await service.submit(sid, "future question", request_id="second")
        await service.wait(second["turn_id"])
        parent = await service.events(sid)
        child = await service.fork(sid, turn_id=first["turn_id"])
        third = await service.submit(child["session_id"], "branch", request_id="third")
        await service.wait(third["turn_id"])
        assert not any("future" in str(message.content) for message in model.seen[-1])
        assert not any(event.get("text") == "future question" for event in await service.history(child["session_id"]))
        user = next(event for event in parent if event["type"] == "message.user")
        edited = await service.fork(sid, message_id=user["message_id"])
        fourth = await service.submit(edited["session_id"], "edited question", request_id="fourth")
        await service.wait(fourth["turn_id"])
        assert [message.content for message in model.seen[-1] if message.type == "human"] == ["edited question"]
        assert await service.events(sid) == parent
    finally:
        await service.close()


async def test_running_compact_waits_for_tool_receipt_and_summarizes_once(tmp_path):
    from workflowweave.agent.tools.declaration import ToolDeclaration, schema
    started, release = asyncio.Event(), asyncio.Event()

    async def invoke(arguments, context):
        started.set()
        await release.wait()
        return {"status": "success", "text": "receipt"}

    model = ScriptedModel(responses=[AIMessage(content="old answer " * 100), AIMessage(content="", tool_calls=[{
        "id": "held", "name": "held", "args": {},
    }]), AIMessage(content="official summary"), AIMessage(content="final answer")])
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model,
                           config=AgentConfig(keep_tokens=40),
                           declarations=[ToolDeclaration("held", "held", schema({}), "read", invoke)])
    try:
        sid = (await service.create_session())["session_id"]
        first = await service.submit(sid, "old fact " * 100, request_id="r1")
        await service.wait(first["turn_id"])
        second = await service.submit(sid, "use tool", request_id="r2")
        await asyncio.wait_for(started.wait(), 1)
        assert (await service.compact(sid))["status"] == "queued"
        assert not any(event["type"] == "context.compacted" for event in await service.events(sid))
        release.set()
        await service.wait(second["turn_id"])
        events = await service.events(sid)
        summaries = [event for event in events if event["type"] == "context.compacted"]
        assert len(summaries) == 1
        assert summaries[0]["id"] > next(event["id"] for event in events if event["type"] == "tool.completed")
        assert len(model.seen) == 4
    finally:
        await service.close()


async def test_settings_persist_and_disabled_tool_metadata_does_not_register(tmp_path):
    from workflowweave.config import PluginRegistry
    from workflowweave.models import SystemConfig
    registry = PluginRegistry()
    plugin_config = SystemConfig(plugin_dir=str(tmp_path / "plugins"))
    registry.update_plugin_setting(plugin_config, "tool", "agent_shell", False)
    await registry.discover_plugins(plugin_config)
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", plugins=registry)
    try:
        await service.initialize()
        config = service.config.model_copy(update={"timezone": "Asia/Shanghai", "trigger_tokens": 170000})
        service.update_config(config)
        shell = next(tool for tool in service.tool_views() if tool["plugin"] == "agent_shell")
        assert shell["enabled"] is False and shell["input_schema"] is None
        assert registry.toolRegister.get("shell") is None
    finally:
        await service.close()
    restored = create_agent_service(tmp_path / "workspace", tmp_path / "runtime")
    try:
        await restored.initialize()
        assert restored.config.timezone == "Asia/Shanghai" and restored.config.trigger_tokens == 170000
    finally:
        await restored.close()


async def test_empty_compact_keeps_source_and_can_accept_first_message(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="ready")])
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model)
    try:
        sid = (await service.create_session(workflow_session_id="run", workflow_result={"result": "frozen"}))["session_id"]
        compact = await service.compact(sid)
        await service.wait(compact["turn_id"])
        events = await service.events(sid)
        assert not any(event["type"] in {"context.compacted", "workflow.input.used"} for event in events)
        assert any(event["type"] == "command.completed" and event["compacted"] is False for event in events)
        turn = await service.submit(sid, "start", request_id="start")
        assert (await service.wait(turn["turn_id"]))["status"] == "completed"
        assert any("frozen" in str(message.content) for message in model.seen[-1])
        metadata = json.loads((service.runtime / "Sessions" / f"{sid}.json").read_text())
        assert metadata["last_checkpoint_at"] and metadata["continuable"]
    finally:
        await service.close()


async def test_failed_boundary_summary_allows_explicit_next_message(tmp_path):
    import pytest

    from tests.agent.test_admission import GatedModel
    from workflowweave.errors import WorkFLowWeaveError

    model = GatedModel(responses=[AIMessage(content="first " * 100), AIMessage(content="second " * 100),
                                  AIMessage(content=""), AIMessage(content="continued")])
    model.release.set()
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime",
                           config=AgentConfig(keep_tokens=1), model_provider=lambda _: model)
    try:
        sid = (await service.create_session())["session_id"]
        first = await service.submit(sid, "first", request_id="first")
        await service.wait(first["turn_id"])
        model.entered.clear()
        model.release.clear()
        second = await service.submit(sid, "second", request_id="second")
        await asyncio.wait_for(model.entered.wait(), 1)
        metadata = json.loads((service.runtime / "Sessions" / f"{sid}.json").read_text())
        assert metadata["status"] == "running" and metadata["turn_id"] == second["turn_id"]
        await service.compact(sid)
        model.release.set()
        with pytest.raises(WorkFLowWeaveError) as error:
            await service.wait(second["turn_id"])
        assert error.value.code == "context_compaction_failed"
        assert not any(event["type"] == "context.compacted" for event in await service.events(sid))
        assert any(event["type"] == "command.failed" for event in await service.events(sid))
        following = await service.submit(sid, "continue with original context", request_id="third")
        assert (await service.wait(following["turn_id"]))["text"] == "continued"
        assert any(message.content == "first" for message in model.seen[-1])
    finally:
        await service.close()
