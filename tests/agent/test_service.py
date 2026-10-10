import asyncio
from collections.abc import AsyncIterator

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field

from tests.agent.helpers import ScriptedModel
from workflowweave.agent.config import AgentConfig
from workflowweave.agent.context.budget import summarization_middleware, validate_request_budget
from workflowweave.agent.context.compaction import summarize_once
from workflowweave.agent.runtime.stream import message_delta
from workflowweave.agent.storage.events import EventLog
from workflowweave.agent.tools.declaration import ToolDeclaration
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.interaction.fastapi.agent import create_agent_service


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
    publish: bool = True

    @property
    def _llm_type(self):
        return "failing-stream-agent-test"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("streaming is required")

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs) -> AsyncIterator[ChatGenerationChunk]:
        self.seen.append(list(messages))
        if self.publish:
            yield ChatGenerationChunk(message=AIMessageChunk(content="partial"))
        await asyncio.sleep(0)
        raise RuntimeError("stream failed after publication")


class PausingStreamModel(FailingStreamModel):
    paused: asyncio.Event = Field(default_factory=asyncio.Event)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs) -> AsyncIterator[ChatGenerationChunk]:
        self.seen.append(list(messages))
        if self.publish:
            yield ChatGenerationChunk(message=AIMessageChunk(content="partial"))
        self.paused.set()
        await asyncio.sleep(30)


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
    service = create_agent_service(
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
    assert all(event["session_id"] == session["session_id"] for event in events)
    assert all(isinstance(event["at"], str) and isinstance(event["data"], dict)
               for event in events)


async def test_topic_title_survives_restart_and_reasoning_delta_is_real(tmp_path):
    workspace, runtime = tmp_path / "workspace", tmp_path / "runtime"
    service = create_agent_service(workspace, runtime, config=AgentConfig(),
                           model_provider=lambda _: ScriptedModel(responses=[]))
    created = await service.create_session(model="scripted")
    changed = await service.set_title(created["session_id"], "  生产告警复盘  ")
    assert changed["title"] == "生产告警复盘"
    with pytest.raises(WorkFLowWeaveError, match="话题名称"):
        await service.set_title(created["session_id"], "  ")
    assert message_delta(AIMessageChunk(
        content="response", additional_kwargs={"reasoning_content": "thinking"},
    )) == {"content": "response", "reasoning": "thinking"}
    assert message_delta(AIMessageChunk(content="response")) == {"content": "response"}
    await service.close()
    restored = create_agent_service(workspace, runtime, config=AgentConfig(),
                            model_provider=lambda _: ScriptedModel(responses=[]))
    await restored.initialize()
    assert (await restored.get_session(created["session_id"]))["title"] == "生产告警复盘"
    await restored.close()


@pytest.mark.parametrize("structured", [False, True])
async def test_completed_reasoning_and_answer_are_persisted_separately(tmp_path, structured):
    response = AIMessage(
        content=[{"type": "thinking", "thinking": "actual reasoning"},
                 {"type": "text", "text": "answer"}] if structured else "answer",
        additional_kwargs={} if structured else {"reasoning_content": "actual reasoning"},
    )
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", config=AgentConfig(),
                           model_provider=lambda _: ScriptedModel(responses=[response]))
    created = await service.create_session(model="scripted")
    accepted = await service.submit(created["session_id"], "hello", request_id="reasoning")
    assert (await service.wait(accepted["turn_id"]))["text"] == "answer"
    events = await service.events(created["session_id"])
    completed = next(event["data"] for event in events if event["type"] == "message.completed")
    assert completed["text"] == "answer"
    assert completed["reasoning"] == "actual reasoning"
    assert completed["incremental"] is False
    await service.close()


async def test_append_queues_behind_running_turn_and_drains_once(tmp_path):
    service = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime",
        config=AgentConfig(),
        model_provider=lambda _: DelayedModel(delay=0.03, response="answer"),
    )
    session = await service.create_session(model="delayed")
    first = await service.submit(session["session_id"], "first", request_id="first")
    queued = await service.append(session["session_id"], "second", request_id="second")
    duplicate = await service.append(session["session_id"], "second", request_id="second")

    assert queued["status"] == "queued"
    assert duplicate["deduplicated"] is True
    await service.wait(first["turn_id"])
    result = await service.wait(queued["turn_id"])
    assert result["status"] == "completed"
    events = await service.events(session["session_id"])
    assert sum(event["type"] == "command.queued" for event in events) == 1
    assert [event["text"] for event in events if event["type"] == "message.user"] == [
        "first", "second",
    ]


async def test_fork_copies_checkpoint_and_keeps_parent_immutable(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="parent"), AIMessage(content="child")])
    service = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime",
        config=AgentConfig(), model_provider=lambda _: model,
    )
    parent = await service.create_session(model="scripted")
    accepted = await service.submit(parent["session_id"], "question", request_id="parent-1")
    await service.wait(accepted["turn_id"])

    child = await service.fork(parent["session_id"])
    assert child["parent_session_id"] == parent["session_id"]
    assert child["parent_turn_id"] == accepted["turn_id"]
    assert child["branch_id"] != parent["branch_id"]
    child_request = await service.submit(child["session_id"], "follow-up", request_id="child-1")
    result = await service.wait(child_request["turn_id"])
    assert result["text"] == "child"
    assert (await service.get_session(parent["session_id"]))["status"] == "completed"
    assert not any(event["type"] == "message.user" and event.get("text") == "follow-up"
                   for event in await service.events(parent["session_id"]))


async def test_event_log_wait_subscribes_without_polling_gap(tmp_path):
    log = EventLog(tmp_path / "runtime", "session")
    await log.initialize()
    waiter = asyncio.create_task(log.wait_for_events(0, wait_seconds=2))
    await asyncio.sleep(0.02)
    appended = await log.append("message.delta", turn_id="turn", content="hi")
    received = await waiter
    assert [event["id"] for event in received] == [appended["id"]]


async def test_agent_tool_execution_is_recorded_before_graph_continues(tmp_path):
    model = ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[{"id": "read-1", "name": "read",
                                            "args": {"path": "Memory/note.md"}}]),
        AIMessage(content="read complete"),
    ])
    service = create_agent_service(
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
    first = create_agent_service(tmp_path / "workspace", tmp_path / "runtime")
    session = await first.create_session(model="scripted")
    await first.repository.log(session["session_id"]).append(
        "turn.started", turn_id="turn_crashed", branch_id=session["branch_id"]
    )
    await first.repository.log(session["session_id"]).reserve_tool(
        "turn_crashed:shell:0", {"command": "touch side-effect"}
    )

    restored = create_agent_service(tmp_path / "workspace", tmp_path / "runtime")
    await restored.initialize()
    current = await restored.get_session(session["session_id"])
    assert current["status"] == "interrupted"
    events = await restored.events(session["session_id"])
    assert any(event["type"] == "turn.interrupted" for event in events)
    assert any(event["type"] == "tool.outcome_unknown" for event in events)


async def test_existing_session_without_checkpoint_is_not_reconstructed(tmp_path):
    first = create_agent_service(tmp_path / "workspace", tmp_path / "runtime")
    session = await first.create_session(model="scripted")
    await first.repository.log(session["session_id"]).append(
        "turn.completed", turn_id="turn_old", text="old"
    )
    await first.close()
    (tmp_path / "runtime" / "checkpoints.sqlite").unlink()

    restored = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime",
        model_provider=lambda _: ScriptedModel(responses=[AIMessage(content="new")]),
    )
    await restored.initialize()
    accepted = await restored.submit(session["session_id"], "continue", request_id="new-request")
    with pytest.raises(WorkFLowWeaveError) as error:
        await restored.wait(accepted["turn_id"])
    assert error.value.code == "checkpoint_missing"
    await restored.close()


async def test_admission_pause_blocks_new_sessions_and_racing_turns(tmp_path):
    service = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime",
        model_provider=lambda _: ScriptedModel(responses=[AIMessage(content="answer")]),
    )
    await service.pause_admission()
    with pytest.raises(WorkFLowWeaveError) as error:
        await service.create_session(model="scripted")
    assert error.value.code == "agent_busy"


async def test_context_budget_includes_fixed_prompt_and_reserved_output():
    config = AgentConfig(context_window=500, output_tokens=100)
    with pytest.raises(WorkFLowWeaveError) as error:
        validate_request_budget(
            [HumanMessage(content="x" * 5_000)], "fixed instructions", [{"name": "read"}], config
        )
    assert error.value.code == "context_budget_exceeded"


async def test_summary_uses_full_prefix_once_and_preserves_tool_pairs():
    config = AgentConfig(context_window=10_000, output_tokens=100,
                         trigger_tokens=8000, keep_tokens=2000,
                         summary_context_window=100_000, summary_max_tokens=100)
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
    service = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime",
        config=AgentConfig(idle_timeout=0.03),
        model_provider=lambda _: DelayedModel(delay=0.2),
    )
    session = await service.create_session(model="delayed")
    accepted = await service.submit(session["session_id"], "hello", request_id="idle-1")
    with pytest.raises(WorkFLowWeaveError) as error:
        await service.wait(accepted["turn_id"])
    assert error.value.code == "model_idle_timeout"
    events = await service.events(session["session_id"])
    failed = [event for event in events if event["type"] == "turn.failed"]
    assert failed and failed[-1]["partial"] is False


async def test_agent_total_timeout_uses_ai_config_and_releases_model_turn(tmp_path):
    from workflowweave.models import AIConfig

    service = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime",
        config=AgentConfig(idle_timeout=1),
        ai_config=AIConfig(
            id="test-ai", provider="mock", models={"delayed": {}}, timeout=0.03,
        ),
        model_provider=lambda _: DelayedModel(delay=0.2),
    )
    session = await service.create_session(model="delayed")
    accepted = await service.submit(session["session_id"], "hello", request_id="total-1")
    with pytest.raises(WorkFLowWeaveError) as error:
        await service.wait(accepted["turn_id"])
    assert error.value.code == "ai_timeout"
    assert service.sessions[session["session_id"]].status == "failed"


@pytest.mark.parametrize("publish", [False, True])
async def test_stream_failure_is_terminal_without_retry_or_duplicate_delta(tmp_path, publish):
    model = FailingStreamModel(publish=publish)
    service = create_agent_service(
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
    assert [event["content"] for event in deltas] == (["partial"] if publish else [])
    assert len(model.seen) == 1
    assert failures and failures[-1]["partial"] is publish
    assert not any(event["type"] == "turn.completed" for event in events)


@pytest.mark.parametrize("publish", [False, True])
@pytest.mark.parametrize("mode", ["idle", "total", "cancel"])
async def test_stream_partial_uses_persisted_deltas_for_timeout_and_cancel(tmp_path, publish, mode):
    from workflowweave.models import AIConfig

    model = PausingStreamModel(publish=publish)
    service = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime",
        config=AgentConfig(idle_timeout=0.1 if mode == "idle" else 1),
        ai_config=AIConfig(id="test-ai", provider="mock", models={"stream": {}},
                           timeout=0.5 if mode == "total" else 10),
        model_provider=lambda _: model,
    )
    session = await service.create_session(model="stream")
    sid = session["session_id"]
    accepted = await service.submit(sid, "hello", request_id="partial-1")
    if mode == "cancel":
        async with asyncio.timeout(5):
            await model.paused.wait()
            if publish:
                log = service.repository.log(sid)
                after = 0
                while True:
                    events = await log.wait_for_events(after)
                    if any(event["type"] == "message.delta" for event in events):
                        break
                    after = events[-1]["id"]
        await service.cancel(sid)
        with pytest.raises(asyncio.CancelledError):
            await service.wait(accepted["turn_id"])
    else:
        with pytest.raises(WorkFLowWeaveError) as error:
            await service.wait(accepted["turn_id"])
        assert error.value.code == ("model_idle_timeout" if mode == "idle" else "ai_timeout")
    events = await service.events(sid)
    terminal = [event for event in events if event["type"] in {"turn.failed", "turn.cancelled"}]
    assert len(terminal) == 1 and terminal[0]["partial"] is publish
    assert len([event for event in events if event["type"] == "message.delta"]) == int(publish)
    assert len(model.seen) == 1


@pytest.mark.parametrize("failure", ["append_error", "cancel_after_commit"])
async def test_partial_tracks_the_durable_delta_when_append_fails_or_is_cancelled(tmp_path, monkeypatch, failure):
    committed = asyncio.Event()
    original_append = EventLog.append

    async def append(log, event_type, **fields):
        if event_type != "message.delta":
            return await original_append(log, event_type, **fields)
        if failure == "append_error":
            raise OSError("delta append failed")
        await original_append(log, event_type, **fields)
        committed.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(EventLog, "append", append)
    service = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime",
        model_provider=lambda _: PausingStreamModel(),
    )
    sid = (await service.create_session(model="stream"))["session_id"]
    accepted = await service.submit(sid, "hello", request_id="append-window")
    if failure == "append_error":
        with pytest.raises(OSError, match="delta append failed"):
            await service.wait(accepted["turn_id"])
    else:
        await asyncio.wait_for(committed.wait(), timeout=5)
        await service.cancel(sid)
        with pytest.raises(asyncio.CancelledError):
            await service.wait(accepted["turn_id"])
    events = await service.events(sid)
    terminal = [event for event in events if event["type"] in {"turn.failed", "turn.cancelled"}]
    assert len(terminal) == 1
    assert terminal[0]["partial"] is (failure == "cancel_after_commit")


async def test_summary_model_timeout_is_scoped_to_summary_call():
    config = AgentConfig(context_window=200, output_tokens=10,
                         trigger_tokens=160, keep_tokens=40,
                         summary_context_window=2000, summary_max_tokens=10)
    model = DelayedModel(delay=0.2)
    middleware = summarization_middleware(model, config, summary_timeout=0.03)
    messages = [
        HumanMessage(content="history " * 200),
        HumanMessage(content="recent"),
    ]
    with pytest.raises(TimeoutError):
        await middleware.abefore_model({"messages": messages}, None)


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
    service = create_agent_service(
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
