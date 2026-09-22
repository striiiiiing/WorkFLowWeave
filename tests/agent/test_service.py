import asyncio
from collections.abc import AsyncIterator

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field

from logagent.agent.builtin.declaration import ToolDeclaration
from logagent.agent.config import AgentConfig
from logagent.agent.context import summarize_once, validate_request_budget
from logagent.agent.events import EventLog
from logagent.agent.service import AgentService
from logagent.errors import LogAgentError
from tests.agent.helpers import ScriptedModel


class DelayedModel(BaseChatModel):
    delay: float
    response: str = "answer"
    seen: list[list[object]] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "delayed-agent-test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return self._result()

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        await asyncio.sleep(self.delay)
        return self._result()

    def _result(self):
        from langchain_core.outputs import ChatGeneration, ChatResult
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.response))])


class FailingStreamModel(BaseChatModel):
    seen: list[list[object]] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "failing-stream-agent-test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("streaming is required")

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs) -> AsyncIterator[ChatGenerationChunk]:
        self.seen.append(list(messages))
        yield ChatGenerationChunk(message=AIMessageChunk(content="partial"))
        await asyncio.sleep(0)
        raise RuntimeError("stream failed after publication")


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
    assert completed[0]["tool_key"].endswith(":read-1")
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


async def test_admission_pause_blocks_new_sessions_and_racing_turns(tmp_path):
    service = AgentService(
        tmp_path / "workspace", tmp_path / "runtime",
        model_provider=lambda _: ScriptedModel(responses=[AIMessage(content="answer")]),
    )
    await service.pause_admission()
    with pytest.raises(LogAgentError) as error:
        await service.create_session(model="scripted")
    assert error.value.code == "agent_busy"


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


async def test_agent_enforces_model_idle_timeout_without_sse_heartbeat(tmp_path):
    service = AgentService(
        tmp_path / "workspace", tmp_path / "runtime",
        config=AgentConfig(idle_timeout=0.03),
        model_provider=lambda _: DelayedModel(delay=0.2),
    )
    session = await service.create_session(model="delayed")
    accepted = await service.submit(session["session_id"], "hello", request_id="idle-1")
    with pytest.raises(LogAgentError) as error:
        await service.wait(accepted["turn_id"])
    assert error.value.code == "model_idle_timeout"
    events = await service.events(session["session_id"])
    failed = [event for event in events if event["type"] == "turn.failed"]
    assert failed and failed[-1]["partial"] is False


async def test_agent_total_timeout_uses_ai_config_and_releases_model_turn(tmp_path):
    from logagent.models import AIConfig

    service = AgentService(
        tmp_path / "workspace", tmp_path / "runtime",
        config=AgentConfig(idle_timeout=1),
        ai_config=AIConfig(
            id="test-ai", provider="mock", models={"delayed": {}}, timeout=0.03,
        ),
        model_provider=lambda _: DelayedModel(delay=0.2),
    )
    session = await service.create_session(model="delayed")
    accepted = await service.submit(session["session_id"], "hello", request_id="total-1")
    with pytest.raises(LogAgentError) as error:
        await service.wait(accepted["turn_id"])
    assert error.value.code == "ai_timeout"
    assert service.sessions[session["session_id"]].status == "failed"


async def test_stream_failure_after_delta_is_terminal_without_retry_or_duplicate_delta(tmp_path):
    model = FailingStreamModel()
    service = AgentService(
        tmp_path / "workspace", tmp_path / "runtime",
        config=AgentConfig(idle_timeout=1), model_provider=lambda _: model,
    )
    session = await service.create_session(model="failing-stream")
    accepted = await service.submit(session["session_id"], "hello", request_id="stream-1")
    with pytest.raises(RuntimeError, match="stream failed"):
        await service.wait(accepted["turn_id"])
    events = await service.events(session["session_id"])
    deltas = [event for event in events if event["type"] == "message.delta"]
    failures = [event for event in events if event["type"] == "turn.failed"]
    assert [event["content"] for event in deltas] == ["partial"]
    assert len(model.seen) == 1
    assert failures and failures[-1]["partial"] is True
    assert not any(event["type"] == "turn.completed" for event in events)


async def test_cancelled_turn_waits_for_tool_cleanup_and_marks_unknown(tmp_path):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def invoke(arguments, context):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {"status": "success"}

    model = ScriptedModel(responses=[AIMessage(
        content="", tool_calls=[{"id": "slow-1", "name": "slow", "args": {}}],
    )])
    service = AgentService(
        tmp_path / "workspace", tmp_path / "runtime",
        config=AgentConfig(idle_timeout=1), model_provider=lambda _: model,
        declarations=[ToolDeclaration(
            "slow", "long running test tool", {"type": "object", "properties": {},
                                                 "additionalProperties": False}, "exclusive", invoke,
        )],
    )
    session = await service.create_session(model="scripted")
    accepted = await service.submit(session["session_id"], "run", request_id="cancel-1")
    await asyncio.wait_for(started.wait(), timeout=1)
    await service.cancel(session["session_id"])
    with pytest.raises(asyncio.CancelledError):
        await service.wait(accepted["turn_id"])
    assert cancelled.is_set()
    events = await service.events(session["session_id"])
    assert any(event["type"] == "tool.outcome_unknown" for event in events)
