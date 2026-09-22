from langchain_core.messages import AIMessage

from logagent.agent.config import AgentConfig
from logagent.agent.events import EventLog
from logagent.agent.service import AgentService
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
    assert any(event["type"] == "tool.outcome_unknown" for event in events)
