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
