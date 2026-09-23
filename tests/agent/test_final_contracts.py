import asyncio
import json

from langchain_core.messages import AIMessage

from logagent.agent.builtin import plugin
from logagent.agent.config import AgentConfig
from logagent.agent.service import AgentService
from tests.agent.helpers import ScriptedModel


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
        "id": "collector-1", "name": "plugin", "args": {"action": "call", "target": "sources:logs"},
    }]), AIMessage(content="done")])]
    gateway = Gateway()
    service = AgentService(tmp_path / "workspace", tmp_path / "runtime",
                           config=AgentConfig(preview_tokens=200),
                           model_provider=lambda _: models[0], declarations=[plugin.plugin])
    # The gateway is injected directly for this isolated graph integration.
    original = service._capture_turn_resources
    from dataclasses import replace
    gateway.catalog = lambda *args, **kwargs: asyncio.sleep(0)
    service._capture_turn_resources = lambda session: replace(original(session), gateway=gateway)
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
    from logagent.agent.builtin.declaration import ToolDeclaration, schema
    started = asyncio.Event()
    release = asyncio.Event()

    async def invoke(arguments, context):
        started.set()
        await release.wait()
        return {"status": "success", "text": "receipt"}

    model = ScriptedModel(responses=[AIMessage(content="", tool_calls=[{
        "id": "call-1", "name": "held", "args": {},
    }]), AIMessage(content="answer to appended input")])
    service = AgentService(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model,
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
    service = AgentService(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model)
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
        assert not service.sessions[sid].pending_appends
    finally:
        await service.close()


async def test_idle_manual_compact_uses_official_summary_and_keeps_history(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="answer " * 100), AIMessage(content="summary")])
    service = AgentService(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model,
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
    service = AgentService(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model)
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
    from logagent.agent.builtin.declaration import ToolDeclaration, schema
    started, release = asyncio.Event(), asyncio.Event()

    async def invoke(arguments, context):
        started.set()
        await release.wait()
        return {"status": "success", "text": "receipt"}

    model = ScriptedModel(responses=[AIMessage(content="old answer " * 100), AIMessage(content="", tool_calls=[{
        "id": "held", "name": "held", "args": {},
    }]), AIMessage(content="official summary"), AIMessage(content="final answer")])
    service = AgentService(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model,
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
