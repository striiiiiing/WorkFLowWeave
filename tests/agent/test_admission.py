import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from langchain_core.messages import AIMessage
from pydantic import Field

from logagent.agent.service import AgentService
from logagent.collection.manager import CollectorManager
from logagent.config import PluginRegistry, ResourceStore
from logagent.errors import LogAgentError
from logagent.models import AIConfig, CollectionContext, SourceConfig, SystemConfig
from tests.agent.helpers import ScriptedModel
from tests.agent.test_gateway import Collector


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
        service = AgentService(root / "workspace", root / "runtime", **kwargs)
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

    async with service._admission_lock:
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
        assert len(service.sessions[sid].pending_appends) == 1


@pytest.mark.parametrize("queued", [True, False])
async def test_failed_admission_does_not_publish_an_in_memory_success(services, monkeypatch, queued):
    model = GatedModel(responses=[AIMessage(content="answer")])
    service = services(model_provider=lambda _: model)
    sid = (await service.create_session(model="test"))["session_id"]
    if queued:
        await service.submit(sid, "running", request_id="first")
        await asyncio.wait_for(model.entered.wait(), 1)
    log = service.sessions[sid].log
    original = log.append

    async def fail_admission(event_type, **fields):
        if event_type == ("command.queued" if queued else "request.accepted"):
            raise OSError("disk full")
        return await original(event_type, **fields)

    monkeypatch.setattr(log, "append", fail_admission)
    with pytest.raises(OSError, match="disk full"):
        await service.append(sid, "new", request_id="rejected")
    assert "rejected" not in service.sessions[sid].request_ids
    assert not service.sessions[sid].pending_appends
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
    first = AgentService(*paths, model_provider=lambda _: ScriptedModel(
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
    restored = AgentService(*paths)
    try:
        await restored.initialize()
        assert await restored.get_session(sid) == completed
        await restored.pause_admission()
        duplicate = await restored.submit(sid, "hello", request_id="r1")
        assert duplicate == {**accepted, "deduplicated": True}
        with pytest.raises(LogAgentError) as error:
            await restored.submit(sid, "different", request_id="r1")
        assert error.value.code == "request_conflict"
        assert not restored._turns
    finally:
        await restored.close()


async def test_concurrent_session_creation_publishes_only_one_session(services):
    service = services()
    async with service._admission_lock:
        requests = [asyncio.create_task(service.create_session(session_id="shared"))
                    for _ in range(2)]
        await asyncio.sleep(0)
    results = await asyncio.gather(*requests, return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert [result.code for result in results if isinstance(result, LogAgentError)] == [
        "session_conflict",
    ]
    assert len(await service.events("shared")) == 1


async def test_turn_uses_one_resource_and_plugin_snapshot_for_model_catalog_and_calls(tmp_path, services):
    collector = Collector()
    plugin_config = SystemConfig(plugin_dir=str(tmp_path / "plugins"))
    registry = PluginRegistry([collector])
    await registry.discover_plugins(plugin_config)
    collectors = CollectorManager(registry.collectorRegister)
    ai = AIConfig(id="test-ai", provider="mock", models={"test": {}}, timeout=600)
    source = SourceConfig(id="records", collector="example", options={"account": "fixed", "limit": 5})
    resources = ResourceStore(
        tmp_path / "resources.json", collector_register=registry.collectorRegister,
        channel_register=registry.channelRegister,
        initial_resources={"sources": [source], "ai": [ai]},
    )
    models = [GatedModel(responses=[
        AIMessage(content="", tool_calls=[{
            "id": "collector-call", "name": "plugin",
            "args": {"action": "call", "target": "sources:records"},
        }]), AIMessage(content="done"),
    ]) for _ in range(2)]
    leases = []

    class AI:
        @asynccontextmanager
        async def lease(self, config, **kwargs):
            index = len(leases)
            leases.append((config, kwargs))
            yield models[index]

    contexts = []

    def collection_context(session):
        value = CollectionContext("agent", session.session_id)
        contexts.append(value)
        return value

    service = services(
        ai_service=AI(), resources=resources, plugins=registry, collectors=collectors,
        channels=object(), collection_context_factory=collection_context,
    )
    sid = (await service.create_session(model="test-ai:test"))["session_id"]
    first = await service.submit(sid, "call", request_id="first")
    await asyncio.wait_for(models[0].entered.wait(), 1)
    generation = registry.generation
    resources.save("sources", source.model_copy(update={"options": {"account": "fixed", "limit": 9}}))
    resources.save("ai", ai.model_copy(update={"timeout": 123}))
    models[0].release.set()
    await service.wait(first["turn_id"])
    first_catalog = service.workspace.runtime / "Catalog" / str(generation) / first["turn_id"]
    old_schema = (first_catalog / "sources-records.json").read_bytes()
    assert json.loads(old_schema)["properties"]["options"]["properties"]["limit"]["default"] == 5
    assert leases[0][0].timeout == 600
    assert collector.calls[0][0]["limit"] == 5
    assert "read" in {tool.name for tool in models[0].bound_tools}

    registry.update_plugin_setting(plugin_config, "tool", "agent_read", False)
    await registry.reload_plugins(plugin_config)
    collectors.reload_register(registry.collectorRegister)
    resources.update_dependencies(collector_register=registry.collectorRegister,
                                  channel_register=registry.channelRegister, validators={})
    second = await service.submit(sid, "again", request_id="second")
    models[1].release.set()
    await service.wait(second["turn_id"])
    new_catalog = service.workspace.runtime / "Catalog" / str(registry.generation) / second["turn_id"]
    new_schema = json.loads((new_catalog / "sources-records.json").read_text())
    assert new_schema["properties"]["options"]["properties"]["limit"]["default"] == 9
    assert leases[1][0].timeout == 123
    assert collector.calls[1][0]["limit"] == 9
    assert len(collector.calls) == 2
    assert "read" not in {tool.name for tool in models[1].bound_tools}
    assert (first_catalog / "sources-records.json").read_bytes() == old_schema
    assert len(contexts) == 2 and all(context.session_id == sid for context in contexts)
