"""Real JSON resources: atomic publication, referential integrity and snapshots."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import orjson
import pytest

from logagent.channel.mock import MockFileChannelType
from logagent.collection.mock import MockCollector
from logagent.config import PluginRegistry, ResourceStore
from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    ChannelConfig,
    SetterTemplate,
    SourceConfig,
    SystemConfig,
    WorkflowDefinition,
)


@pytest.fixture
async def resources(tmp_path):
    registry = PluginRegistry([MockCollector()], builtin_channels=[MockFileChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(
        tmp_path / "resources.json", collector_register=registry.collectorRegister,
        channel_register=registry.channelRegister,
    )
    return store, registry


def seed(store):
    store.save("sources", SourceConfig(id="source", collector="mock"))
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {}}))
    store.save("channels", ChannelConfig(id="channel", channel="mock", options={"path": "out.txt"}))
    definition = WorkflowDefinition(
        id="workflow", sources=["source"], analyses=[{"id": "analysis", "ai": "ai", "model": "model"}],
        channels=["channel"],
    )
    store.save("workflows", definition)
    return definition


def read(store):
    return orjson.loads(Path(store.location).read_bytes())


def edit(store, data):
    Path(store.location).write_bytes(orjson.dumps(data))


async def test_save_reopen_copies_and_original_snapshot(resources):
    store, registry = resources
    definition = seed(store)
    original = store.snapshot("workflow")
    assert Path(original.channels["channel"].options["path"]).is_absolute()
    fetched = store.get("sources", "source")
    fetched.options["records"] = []
    assert store.get("sources", "source").options != fetched.options
    store.list("workflows")[0].sources.clear()
    assert store.get("workflows", "workflow") == definition
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {"reasoning_effort": "high"}}))
    assert original.ai["ai"].models == {"model": {}}
    reopened = ResourceStore(store.location, collector_register=registry.collectorRegister,
                             channel_register=registry.channelRegister)
    assert reopened.snapshot("workflow").ai["ai"].models == {"model": {"reasoning_effort": "high"}}
    assert set(read(store)) == {"format_version", "sources", "setters", "ai", "channels", "workflows"}


async def test_create_replace_and_unknown_fields(resources):
    store, _ = resources
    value = AIConfig(id="ai", provider="mock", models={"model": {}})
    with pytest.raises(LogAgentError, match="不存在"):
        store.save("ai", value, mode="replace")
    store.save("ai", value, mode="create")
    with pytest.raises(LogAgentError, match="已存在"):
        store.save("ai", value, mode="create")
    before = read(store)
    with pytest.raises(LogAgentError):
        store.save("ai", {**value.model_dump(), "unknown": "secret"})
    with pytest.raises(LogAgentError):
        store.save("ai", value, mode="bad")
    assert read(store) == before


@pytest.mark.parametrize("kind,ident", [("sources", "source"), ("ai", "ai"), ("channels", "channel")])
async def test_referenced_resources_cannot_be_deleted(resources, kind, ident):
    store, _ = resources
    seed(store)
    before = read(store)
    with pytest.raises(LogAgentError) as caught:
        store.delete(kind, ident)
    assert caught.value.code == "reference_conflict"
    assert read(store) == before
    store.delete("workflows", "workflow")
    store.delete(kind, ident)
    assert store.get(kind, ident) is None


async def test_template_reference_survives_and_updates_future_snapshots(resources):
    store, _ = resources
    seed(store)
    template = SetterTemplate(id="template", collector="mock", setters={"fields": ["message"]})
    store.save("setters", template)
    source = SourceConfig(id="source", collector="mock", template="template")
    store.save("sources", source)
    original = store.snapshot("workflow")
    assert store.get("sources", "source").template == "template"
    assert store.get("sources", "source").setters == {}
    template.setters = {"fields": ["level"]}
    store.save("setters", template)
    assert store.snapshot("workflow").sources["source"].setters["fields"] == ["level"]
    assert original.sources["source"].setters["fields"] == ["message"]
    source.setters = {"fields": []}
    store.save("sources", source)
    assert store.snapshot("workflow").sources["source"].setters["fields"] == []
    with pytest.raises(LogAgentError) as caught:
        store.delete("setters", "template")
    assert caught.value.code == "reference_conflict"
    with pytest.raises(LogAgentError):
        store.save("setters", SetterTemplate(id="template", collector="missing"))


async def test_invalid_template_update_rejects_entire_candidate(resources):
    store, _ = resources
    seed(store)
    store.save("setters", SetterTemplate(id="t", collector="mock", setters={"fields": ["message"]}))
    store.save("sources", SourceConfig(id="source", collector="mock", template="t"))
    before = read(store)
    with pytest.raises(LogAgentError):
        store.save("setters", SetterTemplate(id="t", collector="mock", setters={"fields": [1]}))
    assert read(store) == before


async def test_resolve_unsaved_definition_and_source_do_not_publish(resources):
    store, _ = resources
    definition = seed(store)
    definition.id = "unsaved"
    before = read(store)
    assert store.resolve(definition).workflow.id == "unsaved"
    assert store.get("workflows", "unsaved") is None
    assert store.resolve(SourceConfig(id="unsaved", collector="mock")).options["mode"] == "success"
    assert read(store) == before
    definition.sources = ["missing"]
    with pytest.raises(LogAgentError):
        store.resolve(definition)
    with pytest.raises(LogAgentError):
        store.resolve(SourceConfig(id="unsaved", collector="mock", setters={"fields": [1]}))


async def test_effective_source_semantics_on_template_update_and_resolve(tmp_path):
    class ProjectingCollector(MockCollector):
        def validate(self, options, setters):
            available = {key for record in options["records"] for key in record}
            if not set(setters.get("fields", [])) <= available:
                raise ValueError("Projection refers to unavailable fields")

    registry = PluginRegistry([ProjectingCollector()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(tmp_path / "resources.json", collector_register=registry.collectorRegister)
    store.save("setters", SetterTemplate(id="t", collector="mock", setters={"fields": ["message"]}))
    store.save("sources", SourceConfig(id="source", collector="mock", template="t"))
    before = read(store)
    with pytest.raises(LogAgentError, match="语义校验"):
        store.save("setters", SetterTemplate(id="t", collector="mock", setters={"fields": ["absent"]}))
    with pytest.raises(LogAgentError, match="语义校验"):
        store.resolve(SourceConfig(id="unsaved", collector="mock", setters={"fields": ["absent"]}))
    assert read(store) == before
    assert store.get("setters", "t").setters == {"fields": ["message"]}
    assert store.get("sources", "unsaved") is None


async def test_missing_plugin_does_not_block_saved_snapshots(resources):
    store, _ = resources
    seed(store)
    reopened = ResourceStore(store.location)
    assert reopened.snapshot("workflow").sources["source"].collector == "mock"
    reopened.save("ai", AIConfig(id="ai", provider="mock", models={"model": {"reasoning_effort": "low"}}))
    with pytest.raises(LogAgentError) as caught:
        reopened.save("sources", SourceConfig(id="new", collector="mock"))
    assert caught.value.code == "capability_missing"
    reopened.delete("workflows", "workflow")
    reopened.delete("sources", "source")


@pytest.mark.parametrize("failure", ["replace", "fsync"])
async def test_write_failure_preserves_disk_and_published_view(resources, monkeypatch, failure):
    store, _ = resources
    seed(store)
    before = await asyncio.to_thread(Path(store.location).read_bytes)
    def fail(*args):
        raise OSError("fake-private-path")
    monkeypatch.setattr(f"logagent.config.store.os.{failure}", fail)
    with pytest.raises(LogAgentError) as caught:
        store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {"reasoning_effort": "low"}}))
    assert "fake-private" not in caught.value.info.model_dump_json()
    assert await asyncio.to_thread(Path(store.location).read_bytes) == before
    assert store.get("ai", "ai").models == {"model": {}}
    assert not list(Path(store.location).parent.glob(".resources-*"))


async def test_reload_candidate_failure_then_success_and_relative_path(resources):
    store, registry = resources
    seed(store)
    data = read(store)
    invalid = deepcopy(data)
    invalid["workflows"]["workflow"]["sources"] = ["missing"]
    edit(store, invalid)
    with pytest.raises(LogAgentError):
        store.reload_resources()
    assert store.snapshot("workflow").workflow.sources == ["source"]
    data["channels"]["channel"]["options"]["path"] = "relative/next.txt"
    data["ai"]["ai"]["models"] = {"model": {"reasoning_effort": "high"}}
    edit(store, data)
    store.reload_resources()
    expected = str(Path(store.location).parent / "relative/next.txt")
    assert store.snapshot("workflow").channels["channel"].options["path"] == expected
    assert read(store)["channels"]["channel"]["options"]["path"] == expected
    # Opening a manually edited valid document also fixes its effective paths.
    data["channels"]["channel"]["options"]["path"] = "manual.txt"
    edit(store, data)
    reopened = ResourceStore(store.location, collector_register=registry.collectorRegister,
                             channel_register=registry.channelRegister)
    assert reopened.snapshot("workflow").channels["channel"].options["path"] == str(Path(store.location).parent / "manual.txt")


@pytest.mark.parametrize("change", ["unknown", "version", "key", "missing_set", "duplicate", "sqlite"])
async def test_invalid_document_never_becomes_an_empty_store(resources, change):
    store, _ = resources
    seed(store)
    data = read(store)
    if change == "unknown":
        data["extra"] = "secret"
    elif change == "version":
        data["format_version"] = 2
    elif change == "key":
        data["ai"]["ai"]["id"] = "different"
    elif change == "missing_set":
        del data["channels"]
    if change == "duplicate":
        await asyncio.to_thread(Path(store.location).write_text, '{"format_version":1,"format_version":1}')
    elif change == "sqlite":
        await asyncio.to_thread(Path(store.location).write_bytes, b"SQLite format 3\x00not-json")
    else:
        edit(store, data)
    with pytest.raises(LogAgentError):
        ResourceStore(store.location)


async def test_parallel_writes_and_snapshots_use_one_complete_view(resources):
    store, _ = resources
    seed(store)
    def change(index):
        store.save("ai", AIConfig(id=f"a{index}", provider="mock", models={str(index): {}}))
        snap = store.snapshot("workflow")
        assert set(snap.ai) == {"ai"} and set(snap.sources) == {"source"}
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(change, range(24)))
    assert len(store.list("ai")) == 25
    assert len(ResourceStore(store.location).list("ai")) == 25


async def test_injected_validation_sees_final_options_once(resources):
    store, registry = resources
    seen = []
    def validate(channel):
        seen.append(deepcopy(channel.options))
        channel.options["path"] = "mutated-by-validator"
    store.update_dependencies(collector_register=registry.collectorRegister,
                              channel_register=registry.channelRegister,
                              validators={"channels": validate})
    result = store.save("channels", ChannelConfig(id="channel", channel="mock", options={"path": "relative.txt"}))
    assert len(seen) == 1
    assert seen[0]["path"] == str(Path(store.location).parent / "relative.txt")
    assert result.options == seen[0]

    before = read(store)
    with pytest.raises(LogAgentError):
        store.save("channels", ChannelConfig(id="channel", channel="mock", options={"path": "relative.txt", "unknown": True}))
    assert read(store) == before


@pytest.mark.parametrize("reference", ["analysis", "fan_in"])
async def test_removing_referenced_model_rejects_entire_resource_candidate(resources, reference):
    store, _ = resources
    definition = seed(store)
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {}, "summary": {}}))
    if reference == "fan_in":
        from logagent.models import FanInConfig
        definition.fan_in = FanInConfig(ai="ai", model="summary")
        store.save("workflows", definition)
    before = await asyncio.to_thread(Path(store.location).read_bytes)
    original = store.snapshot("workflow")
    remaining = {"summary": {}} if reference == "analysis" else {"model": {}}
    with pytest.raises(LogAgentError):
        store.save("ai", AIConfig(id="ai", provider="mock", models=remaining))
    assert await asyncio.to_thread(Path(store.location).read_bytes) == before
    current = store.snapshot("workflow")
    assert current.ai == original.ai
    assert current.workflow == original.workflow
