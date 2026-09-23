import asyncio
from contextlib import asynccontextmanager

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from logagent.agent.builtin.declaration import ToolDeclaration, schema
from logagent.agent.service import AgentService
from tests.agent.helpers import ScriptedModel
from tests.agent.test_admission import GatedModel
from tests.agent.test_admission import services as services


async def test_disconnected_admission_and_waiter_do_not_cancel_the_owned_turn(services, monkeypatch):
    model = GatedModel(responses=[AIMessage(content="answer")])
    service = services(model_provider=lambda _: model)
    sid = (await service.create_session(model="test"))["session_id"]
    writing = asyncio.Event()
    finish_write = asyncio.Event()
    log = service.sessions[sid].log
    original = log.append

    async def blocked_append(event_type, **fields):
        if event_type == "request.accepted":
            writing.set()
            await finish_write.wait()
        return await original(event_type, **fields)

    monkeypatch.setattr(log, "append", blocked_append)
    request = asyncio.create_task(service.submit(sid, "hello", request_id="r1"))
    await asyncio.wait_for(writing.wait(), 1)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    finish_write.set()
    duplicate = await service.submit(sid, "hello", request_id="r1")
    assert duplicate["deduplicated"] is True
    await asyncio.wait_for(model.entered.wait(), 1)
    waiter = asyncio.create_task(service.wait(duplicate["turn_id"]))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not service.sessions[sid].task.done()
    model.release.set()
    assert (await service.wait(duplicate["turn_id"]))["status"] == "completed"
    events = await service.events(sid)
    assert sum(event["type"] == "request.accepted" for event in events) == 1
    assert sum(event["type"] == "turn.completed" for event in events) == 1


async def test_immediate_stop_records_terminal_state_before_acknowledgement(services):
    service = services(model_provider=lambda _: GatedModel(responses=[AIMessage(content="answer")]))
    sid = (await service.create_session(model="test"))["session_id"]
    accepted = await service.submit(sid, "hello", request_id="r1")
    stopped = await service.cancel(sid)
    assert stopped["status"] == "cancelled"
    with pytest.raises(asyncio.CancelledError):
        await service.wait(accepted["turn_id"])
    assert (await service.events(sid))[-1]["type"] == "turn.cancelled"
    assert not any(not task.done() for task in service._turns.values())


async def test_model_lease_spans_model_tool_model_and_exits_after_completion(services):
    active = False
    transitions = []
    model = ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[{"id": "effect-1", "name": "effect", "args": {}}]),
        AIMessage(content="answer"),
    ])

    @asynccontextmanager
    async def provider(_):
        nonlocal active
        active = True
        transitions.append("leased")
        try:
            yield model
        finally:
            assert len(model.seen) == 2
            transitions.append("released")
            active = False

    async def invoke(arguments, context):
        assert active
        assert len(model.seen) == 1
        transitions.append("tool")
        return {"status": "success"}

    service = services(model_provider=provider, declarations=[
        ToolDeclaration("effect", "Effect", schema({}), "exclusive", invoke),
    ])
    sid = (await service.create_session(model="test"))["session_id"]
    accepted = await service.submit(sid, "run", request_id="r1")
    assert (await service.wait(accepted["turn_id"]))["text"] == "answer"
    assert transitions == ["leased", "tool", "released"]
    assert not active


async def test_stop_disconnect_and_repeated_stop_preserve_cleanup_inside_model_lease(services):
    active = False
    tool_started = asyncio.Event()
    cleaning = asyncio.Event()
    finish_cleanup = asyncio.Event()
    cleaned = asyncio.Event()
    model = ScriptedModel(responses=[AIMessage(content="", tool_calls=[
        {"id": "effect-1", "name": "effect", "args": {}},
    ])])

    @asynccontextmanager
    async def provider(_):
        nonlocal active
        active = True
        try:
            yield model
        finally:
            assert cleaned.is_set()
            active = False

    async def invoke(arguments, context):
        tool_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await finish_cleanup.wait()
            assert active
            cleaned.set()

    service = services(model_provider=provider, declarations=[
        ToolDeclaration("effect", "Effect", schema({}), "exclusive", invoke),
    ])
    sid = (await service.create_session(model="test"))["session_id"]
    accepted = await service.submit(sid, "run", request_id="r1")
    await asyncio.wait_for(tool_started.wait(), 1)
    stop = asyncio.create_task(service.cancel(sid))
    await asyncio.wait_for(cleaning.wait(), 1)
    stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop
    repeated = asyncio.create_task(service.cancel(sid))
    await asyncio.sleep(0)
    assert active and not repeated.done()
    finish_cleanup.set()
    assert (await asyncio.wait_for(repeated, 1))["status"] == "cancelled"
    with pytest.raises(asyncio.CancelledError):
        await service.wait(accepted["turn_id"])
    assert cleaned.is_set() and not active
    assert service.scheduler.status == {
        "read_concurrency": 4, "write_concurrency": 1, "reading": 0, "writing": 0, "queued": 0,
    }
    events = await service.events(sid)
    unknown = [event for event in events if event["type"] == "tool.outcome_unknown"]
    assert len(unknown) == 1 and unknown[0]["result"] == {"status": "outcome_unknown", "reason": "cancelled"}
    assert unknown[0]["id"] < events[-1]["id"]
    assert events[-1]["type"] == "turn.cancelled"


async def test_cancelled_tool_waiting_for_workspace_lock_never_executes(services, monkeypatch):
    invoked = False
    model = ScriptedModel(responses=[AIMessage(content="", tool_calls=[
        {"id": "effect-1", "name": "effect", "args": {}},
    ])])

    async def invoke(arguments, context):
        nonlocal invoked
        invoked = True
        return {"status": "success"}

    service = services(model_provider=lambda _: model, declarations=[
        ToolDeclaration("effect", "Effect", schema({}), "exclusive", invoke),
    ])
    sid = (await service.create_session(model="test"))["session_id"]
    async with service.scheduler.acquire("exclusive"):
        queued = asyncio.Event()
        acquire = service.scheduler.acquire

        @asynccontextmanager
        async def observe_acquire(execution):
            queued.set()
            async with acquire(execution):
                yield

        monkeypatch.setattr(service.scheduler, "acquire", observe_acquire)
        accepted = await service.submit(sid, "run", request_id="r1")
        await asyncio.wait_for(queued.wait(), 1)
        assert service.scheduler.queued == 1
        await service.cancel(sid)
        with pytest.raises(asyncio.CancelledError):
            await service.wait(accepted["turn_id"])
        assert service.scheduler.queued == 0
    assert not invoked
    events = await service.events(sid)
    assert not any(event["type"] in {"tool.started", "tool.outcome_unknown"} for event in events)
    assert any(event["type"] == "tool.completed" and event["result"]["status"] == "cancelled"
               for event in events)
    assert events[-1]["type"] == "turn.cancelled"
    async with service.scheduler.acquire("exclusive"):
        assert service.scheduler.writing == 1


async def test_tool_failure_cleans_sibling_before_releasing_lease(services):
    started = asyncio.Event()
    cleaned = asyncio.Event()
    active = False
    model = ScriptedModel(responses=[AIMessage(content="", tool_calls=[
        {"id": "slow-1", "name": "slow", "args": {}},
        {"id": "fail-1", "name": "fail", "args": {}},
    ])])

    @asynccontextmanager
    async def provider(_):
        nonlocal active
        active = True
        try:
            yield model
        finally:
            assert cleaned.is_set()
            active = False

    async def slow(arguments, context):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            assert active
            cleaned.set()

    async def fail(arguments, context):
        await started.wait()
        raise RuntimeError("unexpected tool failure")

    service = services(model_provider=provider, declarations=[
        ToolDeclaration("slow", "Slow", schema({}), "read", slow),
        ToolDeclaration("fail", "Fail", schema({}), "read", fail),
    ])
    sid = (await service.create_session(model="test"))["session_id"]
    accepted = await service.submit(sid, "run", request_id="r1")
    with pytest.raises(RuntimeError, match="unexpected tool failure"):
        await asyncio.wait_for(service.wait(accepted["turn_id"]), 1)
    assert cleaned.is_set() and not active and service.scheduler.reading == 0
    assert (await service.events(sid))[-1]["type"] == "turn.failed"


async def test_agent_sqlite_thread_is_independent_of_workflow_and_resumes_context(tmp_path):
    sid = "same-thread-id"
    config = {"configurable": {"thread_id": sid}}
    paths = (tmp_path / "workspace", tmp_path / "runtime")
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "workflow.sqlite")) as workflow:
        workflow_graph = create_agent(
            ScriptedModel(responses=[AIMessage(content="workflow only")]), checkpointer=workflow,
        )
        await workflow_graph.ainvoke({"messages": [HumanMessage(content="workflow question")]}, config)
        before = await workflow.aget_tuple(config)
        first = AgentService(*paths, model_provider=lambda _: ScriptedModel(
            responses=[AIMessage(content="agent answer")],
        ))
        try:
            await first.create_session(session_id=sid, model="test")
            accepted = await first.submit(sid, "agent question", request_id="r1")
            await first.wait(accepted["turn_id"])
            agent_state = await first.checkpointer.aget_tuple(config)
            assert [message.content for message in agent_state.checkpoint["channel_values"]["messages"]] == [
                "agent question", "agent answer",
            ]
            assert len([item async for item in first.checkpointer.alist(config)]) > 1
        finally:
            await first.close()
        model = ScriptedModel(responses=[AIMessage(content="continued")])
        restored = AgentService(*paths, model_provider=lambda _: model)
        try:
            await restored.initialize()
            accepted = await restored.submit(sid, "follow up", request_id="r2")
            await restored.wait(accepted["turn_id"])
            assert [message.content for message in model.seen[0][1:]] == [
                "agent question", "agent answer", "follow up",
            ]
            assert await workflow.aget_tuple(config) == before
        finally:
            await restored.close()
