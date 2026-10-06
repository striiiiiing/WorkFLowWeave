"""JSON 资源存储的原子发布、引用和快照测试。

真实临时资源文件配合注册表验证保存/重开、旧采集资源拒绝、创建/替换、引用约束
及不可变快照；并发提交和写入故障检查磁盘与已发布视图一致。
验证失败保留旧有效资源，不将损坏文件作为空存储。
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import orjson
import pytest

from logagent.config import PluginRegistry, ResourceStore
from logagent.config.migrations import RESOURCE_FORMAT_VERSION
from logagent.errors import LogAgentError
from logagent.lifecycle.resources import LifecycleResourceStore
from logagent.models import (
    AIConfig,
    ChannelConfig,
    SourceConfig,
    SystemConfig,
    WorkflowDefinition,
)
from plugins.channel.file.channel import FileChannelType
from tests.fixtures.collectors import MockCollector


@pytest.fixture
async def resources(tmp_path):
    registry = PluginRegistry([MockCollector()], builtin_channels=[FileChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(
        tmp_path / "resources.json", collector_register=registry.collectorRegister,
        channel_register=registry.channelRegister,
    )
    return store, registry


def seed(store):
    store.save("sources", SourceConfig(id="source", call={
        "kind": "cli", "mode": "argv", "executable": "printf", "argv": ["%s", "example"],
    }))
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {}}))
    store.save("channels", ChannelConfig(id="channel", channel="file", options={"path": "out.txt"}))
    definition = WorkflowDefinition(
        id="workflow", sources=["source"], analyses=[{"user_prompt": "analyze input", "id": "analysis", "ai": "ai", "model": "model"}],
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
    fetched.call.argv.append("changed")
    assert store.get("sources", "source").call.argv != fetched.call.argv
    store.list("workflows")[0].sources.clear()
    assert store.get("workflows", "workflow") == definition
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {"reasoning_effort": "high"}}))
    assert original.ai["ai"].models == {"model": {}}
    reopened = ResourceStore(store.location, collector_register=registry.collectorRegister,
                             channel_register=registry.channelRegister)
    assert reopened.snapshot("workflow").ai["ai"].models == {"model": {"reasoning_effort": "high"}}
    assert set(read(store)) == {"format_version", "sources", "mcp_servers", "ai", "channels", "workflows"}


@pytest.mark.parametrize("version", [1, 2, 3])
async def test_legacy_collection_resources_require_explicit_rebuild(resources, version):
    store, _ = resources
    original = seed(store)
    data = read(store)
    data["format_version"] = version
    data["sources"]["source"] = {"id": "source", "collector": "mock"}
    if version < 3:
        data["setters"] = {"legacy": {"id": "legacy", "collector": "mock"}}
        data.pop("mcp_servers")
    edit(store, data)
    before = await asyncio.to_thread(Path(store.location).read_bytes)
    with pytest.raises(LogAgentError) as error:
        store.reload_resources()
    assert error.value.code == "collection_migration_required"
    with pytest.raises(LogAgentError) as error:
        ResourceStore(store.location)
    assert error.value.code == "collection_migration_required"
    assert await asyncio.to_thread(Path(store.location).read_bytes) == before
    assert store.snapshot("workflow").workflow == original


async def test_save_many_updates_model_and_workflow_atomically(resources):
    store, registry = resources
    definition = seed(store)
    before = await asyncio.to_thread(Path(store.location).read_bytes)
    upgraded = AIConfig(id="ai", provider="mock", models={"next": {}})
    definition.analyses[0].model = "next"

    with pytest.raises(LogAgentError):
        store.save("ai", upgraded)
    assert await asyncio.to_thread(Path(store.location).read_bytes) == before

    invalid = definition.model_copy(update={"sources": ["missing"]})
    with pytest.raises(LogAgentError):
        store.save_many({"ai": [upgraded], "workflows": [invalid]})
    assert await asyncio.to_thread(Path(store.location).read_bytes) == before
    assert store.snapshot("workflow").workflow.analyses[0].model == "model"

    store.save_many({"ai": [upgraded], "workflows": [definition]})
    reopened = ResourceStore(
        store.location, collector_register=registry.collectorRegister,
        channel_register=registry.channelRegister,
    )
    assert reopened.snapshot("workflow").workflow.analyses[0].model == "next"
    assert reopened.snapshot("workflow").ai["ai"].models == {"next": {}}


async def test_lifecycle_batch_refreshes_once_after_success(resources, tmp_path):
    _, registry = resources
    refreshed = []
    store = LifecycleResourceStore(
        tmp_path / "batch-resources.json",
        collector_register=registry.collectorRegister,
        channel_register=registry.channelRegister,
        on_change=lambda: refreshed.append(True),
    )
    store.save_many({
        "sources": [SourceConfig(id="source", call={"kind": "cli", "mode": "argv", "executable": "printf", "argv": ["%s", "example"]})],
        "ai": [AIConfig(id="ai", provider="mock", models={"model": {}})],
    })
    assert refreshed == [True]
    with pytest.raises(LogAgentError):
        store.save_many({"workflows": [WorkflowDefinition(
            id="broken", sources=["missing"],
            analyses=[{"user_prompt": "analyze input", "id": "analysis", "ai": "ai", "model": "model"}],
        )]})
    assert refreshed == [True]
    assert store.list("workflows") == []
    store.save_many({"ai": []})
    assert refreshed == [True]


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


async def test_resolve_unsaved_definition_and_source_do_not_publish(resources):
    store, _ = resources
    definition = seed(store)
    definition.id = "unsaved"
    before = read(store)
    assert store.resolve(definition).workflow.id == "unsaved"
    assert store.get("workflows", "unsaved") is None
    source = SourceConfig(id="unsaved", call={
        "kind": "cli", "mode": "argv", "executable": "printf", "argv": ["%s", "unsaved"],
    })
    assert store.resolve(source).call.argv == ["%s", "unsaved"]
    assert read(store) == before
    definition.sources = ["missing"]
    with pytest.raises(LogAgentError):
        store.resolve(definition)
    with pytest.raises(LogAgentError):
        store.resolve(SourceConfig(id="unsaved", call={
            "kind": "mcp", "server": "missing", "tool": "echo",
        }))


async def test_cli_snapshots_do_not_require_collector_registry(resources):
    store, _ = resources
    seed(store)
    reopened = ResourceStore(store.location)
    assert reopened.snapshot("workflow").sources["source"].call.kind == "cli"
    reopened.save("ai", AIConfig(id="ai", provider="mock", models={"model": {"reasoning_effort": "low"}}))
    with pytest.raises(LogAgentError) as caught:
        reopened.save("sources", SourceConfig(id="new", call={
            "kind": "mcp", "server": "missing", "tool": "echo",
        }))
    assert caught.value.code == "invalid_reference"
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
        data["format_version"] = RESOURCE_FORMAT_VERSION + 1
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
    result = store.save("channels", ChannelConfig(id="channel", channel="file", options={"path": "relative.txt"}))
    assert len(seen) == 1
    assert seen[0]["path"] == str(Path(store.location).parent / "relative.txt")
    assert result.options == seen[0]

    before = read(store)
    with pytest.raises(LogAgentError):
        store.save("channels", ChannelConfig(id="channel", channel="file", options={"path": "relative.txt", "unknown": True}))
    assert read(store) == before


@pytest.mark.parametrize("reference", ["analysis", "fan_in"])
async def test_removing_referenced_model_rejects_entire_resource_candidate(resources, reference):
    store, _ = resources
    definition = seed(store)
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {}, "summary": {}}))
    if reference == "fan_in":
        from logagent.models import FanInConfig
        definition.fan_in = FanInConfig(user_prompt="summarize results", ai="ai", model="summary", reuse_from=None)
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
