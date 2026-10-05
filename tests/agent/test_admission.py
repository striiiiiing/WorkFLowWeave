import asyncio

import pytest
from langchain_core.messages import AIMessage
from pydantic import Field

from logagent.errors import LogAgentError
from logagent.interaction.fastapi.agent import create_agent_service
from tests.agent.helpers import ScriptedModel


class GatedModel(ScriptedModel):
    entered: asyncio.Event = Field(default_factory=asyncio.Event)
    release: asyncio.Event = Field(default_factory=asyncio.Event)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.entered.set()
        await self.release.wait()
        return await super()._agenerate(messages, stop, run_manager, **kwargs)


@pytest.fixture
async def services(tmp_path):
    owned = []

    def create(**kwargs):
        root = tmp_path / str(len(owned))
        service = create_agent_service(root / "workspace", root / "runtime", **kwargs)
        owned.append(service)
        return service

    yield create
    for service in reversed(owned):
        await service.close()


@pytest.mark.parametrize("method", ["submit", "append"])
@pytest.mark.parametrize("same_text", [True, False])
async def test_racing_request_ids_share_one_durable_admission(services, method, same_text):
    model = GatedModel(responses=[AIMessage(content="answer"), AIMessage(content="second")])
    service = services(model_provider=lambda _: model)
    sid = (await service.create_session(model="test"))["session_id"]
    if method == "append":
        await service.submit(sid, "already running", request_id="first")
        await asyncio.wait_for(model.entered.wait(), 1)

    async with service.turns.admission_lock:
        first = asyncio.create_task(getattr(service, method)(sid, "hello", request_id="shared"))
        second = asyncio.create_task(getattr(service, method)(
            sid, "hello" if same_text else "different", request_id="shared",
        ))
        await asyncio.sleep(0)
    accepted = await first
    if same_text:
        duplicate = await second
        assert duplicate["turn_id"] == accepted["turn_id"]
        assert duplicate["deduplicated"] is True
    else:
        with pytest.raises(LogAgentError) as error:
            await second
        assert error.value.code == "request_conflict"
    events = await service.events(sid)
    assert sum(event.get("request_id") == "shared" for event in events) == 1
    if method == "append":
        assert len(service.turns.current(sid).pending_appends) == 1


@pytest.mark.parametrize("queued", [True, False])
async def test_failed_admission_does_not_publish_an_in_memory_success(services, monkeypatch, queued):
    model = GatedModel(responses=[AIMessage(content="answer")])
    service = services(model_provider=lambda _: model)
    sid = (await service.create_session(model="test"))["session_id"]
    if queued:
        await service.submit(sid, "running", request_id="first")
        await asyncio.wait_for(model.entered.wait(), 1)
    log = service.repository.log(sid)
    original = log.append

    async def fail_admission(event_type, **fields):
        if event_type == ("command.queued" if queued else "request.accepted"):
            raise OSError("disk full")
        return await original(event_type, **fields)

    monkeypatch.setattr(log, "append", fail_admission)
    with pytest.raises(OSError, match="disk full"):
        await service.append(sid, "new", request_id="rejected")
    assert "rejected" not in service.repository.requests(sid)
    assert not service.turns.current(sid).pending_appends
    assert not any(event.get("request_id") == "rejected" for event in await service.events(sid))


async def test_sessions_generate_concurrently_but_each_accepts_only_one_turn(services):
    models = [GatedModel(responses=[AIMessage(content="answer")]) for _ in range(2)]
    service = services(model_provider=lambda session: models[int(session.model)])
    sessions = [(await service.create_session(model=str(i)))["session_id"] for i in range(2)]
    turns = await asyncio.gather(*[
        service.submit(sid, "hello", request_id="first") for sid in sessions
    ])
    await asyncio.wait_for(asyncio.gather(*(model.entered.wait() for model in models)), 1)
    with pytest.raises(LogAgentError) as error:
        await service.submit(sessions[0], "another", request_id="second")
    assert error.value.code == "session_busy"
    for model in models:
        model.release.set()
    assert all(result["status"] == "completed" for result in await asyncio.gather(*[
        service.wait(turn["turn_id"]) for turn in turns
    ]))


async def test_request_id_and_thread_timestamps_survive_restart(tmp_path):
    paths = (tmp_path / "workspace", tmp_path / "runtime")
    first = create_agent_service(*paths, model_provider=lambda _: ScriptedModel(
        responses=[AIMessage(content="answer")],
    ))
    try:
        sid = (await first.create_session(model="test"))["session_id"]
        accepted = await first.submit(sid, "hello", request_id="r1")
        await first.wait(accepted["turn_id"])
        completed = await first.get_session(sid)
        assert completed["updated_at"] > completed["created_at"]
        assert completed["updated_at"] == (await first.events(sid))[-1]["at"]
    finally:
        await first.close()
    restored = create_agent_service(*paths)
    try:
        await restored.initialize()
        assert await restored.get_session(sid) == completed
        await restored.pause_admission()
        duplicate = await restored.submit(sid, "hello", request_id="r1")
        assert duplicate == {**accepted, "deduplicated": True}
        with pytest.raises(LogAgentError) as error:
            await restored.submit(sid, "different", request_id="r1")
        assert error.value.code == "request_conflict"
        assert not restored.turns.tasks
    finally:
        await restored.close()


async def test_concurrent_session_creation_publishes_only_one_session(services):
    service = services()
    async with service.turns.admission_lock:
        requests = [asyncio.create_task(service.create_session(session_id="shared"))
                    for _ in range(2)]
        await asyncio.sleep(0)
    results = await asyncio.gather(*requests, return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert [result.code for result in results if isinstance(result, LogAgentError)] == [
        "session_conflict",
    ]
    assert len(await service.events("shared")) == 1
