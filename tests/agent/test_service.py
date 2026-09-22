import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from logagent.agent.config import AgentConfig
from logagent.agent.context import summarize_once, validate_request_budget
from logagent.agent.events import EventLog
from logagent.agent.service import AgentService
from logagent.errors import LogAgentError
from tests.agent.helpers import ScriptedModel


async def test_event_log_reuses_completed_tool_and_marks_restart_unknown(tmp_path):
    log = EventLog(tmp_path / "runtime", "session")
    await log.initialize()
    first = await log.reserve_tool("turn:read:0", {"path": "Memory/a.md"})
    assert first.status == "started"
    await log.complete_tool("turn:read:0", {"path": "Memory/a.md"}, {"status": "success"})
    reused = await log.reserve_tool("turn:read:0", {"path": "Memory/a.md"})
    assert reused.status == "tool.completed"
    assert reused.result == {"status": "success"}

    await log.reserve_tool("turn:shell:0", {"command": "touch x"})
    unknown = await log.recover_interrupted()
    assert unknown == ["turn:shell:0"]
    assert any(event["type"] == "tool.outcome_unknown" for event in await log.replay())


async def test_event_log_waits_for_active_key_across_instances(tmp_path):
    first = EventLog(tmp_path / "runtime", "session")
    second = EventLog(tmp_path / "runtime", "session")
    await first.initialize()
    await second.initialize()
    arguments = {"path": "Memory/shared.md"}
    assert (await first.reserve_tool("turn:write:call-1", arguments)).status == "started"

    waiter = asyncio.create_task(second.wait_for_tool("turn:write:call-1", arguments, wait_timeout=1))
    await asyncio.sleep(0.05)
    assert not waiter.done()
    await first.complete_tool("turn:write:call-1", arguments, {"status": "success"})
    result = await waiter
    assert result.status == "tool.completed"
    assert result.result == {"status": "success"}


async def test_agent_service_is_idempotent_and_runs_one_turn(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="answer")])
    service = AgentService(
        tmp_path / "workspace", tmp_path / "runtime", config=AgentConfig(),
        model_provider=lambda _: model,
    )
    session = await service.create_session(model="scripted")
    accepted = await service.submit(session["session_id"], "hello", request_id="request-1")
    duplicate = await service.submit(session["session_id"], "hello", request_id="request-1")
    assert duplicate["turn_id"] == accepted["turn_id"]
    result = await service.wait(accepted["turn_id"])
    assert result == {"turn_id": accepted["turn_id"], "status": "completed", "text": "answer"}
    events = await service.events(session["session_id"])
    assert [event["type"] for event in events][-1] == "turn.completed"


async def test_agent_tool_execution_is_recorded_before_graph_continues(tmp_path):
    model = ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[{"id": "read-1", "name": "read",
                                            "args": {"path": "Memory/note.md"}}]),
        AIMessage(content="read complete"),
    ])
    service = AgentService(
        tmp_path / "workspace", tmp_path / "runtime", config=AgentConfig(),
        model_provider=lambda _: model,
    )
    await service.initialize()
    await service.workspace.write("Memory/note.md", "overwrite", "hello\n")
    session = await service.create_session(model="scripted")
    accepted = await service.submit(session["session_id"], "read it", request_id="request-1")
    result = await service.wait(accepted["turn_id"])
    assert result["text"] == "read complete"
    completed = [event for event in await service.events(session["session_id"])
                 if event["type"] == "tool.completed"]
    assert len(completed) == 1
    assert completed[0]["result"]["content"] == "hello\n"


async def test_service_restart_marks_started_turn_and_tool_as_interrupted(tmp_path):
    first = AgentService(tmp_path / "workspace", tmp_path / "runtime")
    session = await first.create_session(model="scripted")
    await first.sessions[session["session_id"]].log.append(
        "turn.started", turn_id="turn_crashed", branch_id=session["branch_id"]
    )
    await first.sessions[session["session_id"]].log.reserve_tool(
        "turn_crashed:shell:0", {"command": "touch side-effect"}
    )

    restored = AgentService(tmp_path / "workspace", tmp_path / "runtime")
    await restored.initialize()
    current = await restored.get_session(session["session_id"])
    assert current["status"] == "interrupted"
    events = await restored.events(session["session_id"])
    assert any(event["type"] == "turn.interrupted" for event in events)
    assert any(event["type"] == "tool.outcome_unknown" for event in events)


async def test_existing_session_without_checkpoint_is_not_reconstructed(tmp_path):
    first = AgentService(tmp_path / "workspace", tmp_path / "runtime")
    session = await first.create_session(model="scripted")
    await first.sessions[session["session_id"]].log.append(
        "turn.completed", turn_id="turn_old", text="old"
    )
    await first.close()
    (tmp_path / "runtime" / "checkpoints.sqlite").unlink()

    restored = AgentService(
        tmp_path / "workspace", tmp_path / "runtime",
        model_provider=lambda _: ScriptedModel(responses=[AIMessage(content="new")]),
    )
    await restored.initialize()
    accepted = await restored.submit(session["session_id"], "continue", request_id="new-request")
    with pytest.raises(LogAgentError) as error:
        await restored.wait(accepted["turn_id"])
    assert error.value.code == "checkpoint_missing"
    await restored.close()


async def test_context_budget_includes_fixed_prompt_and_reserved_output():
    config = AgentConfig(context_window=500, output_tokens=100)
    with pytest.raises(LogAgentError) as error:
        validate_request_budget(
            [HumanMessage(content="x" * 5_000)], "fixed instructions", [{"name": "read"}], config
        )
    assert error.value.code == "context_budget_exceeded"


async def test_summary_uses_full_prefix_once_and_preserves_tool_pairs():
    config = AgentConfig(context_window=10_000, output_tokens=100)
    messages = [
        HumanMessage(content="early fact " + "history " * 12_000),
        AIMessage(content="", tool_calls=[{"id": "call-1", "name": "read", "args": {}}]),
    ]
    from langchain_core.messages import ToolMessage
    messages.append(ToolMessage(content="read result", tool_call_id="call-1"))
    model = ScriptedModel(responses=[AIMessage(content="summary")])
    compacted = await summarize_once(model, messages, config)
    assert compacted and model.seen
    assert any("early fact" in message.content for message in model.seen[0])
