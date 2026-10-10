"""配置覆盖从资源绑定到采集、通知与恢复的跨模块测试。

用真实 ResourceStore、注册表和管理器验证MCP 参数覆盖、显式空值、
绑定引用完整性、账户/调用字段作用域及失败提交的原子性；再经 Workflow、
SQLite 和本地文件渠道验证不同绑定相互隔离，恢复仍使用原快照。
模型使用注入的 LangChain 替身；邮件配置仅校验，不向真实收件人投递。
"""

import asyncio
from copy import deepcopy

import pytest
from pydantic import ValidationError

from tests.fixtures.sources import message_call
from tests.workflow_ai_helpers import TestChannelFactory
from workflowweave.ai import AIService
from workflowweave.channel import ChannelManager
from workflowweave.collection import CollectorManager
from workflowweave.config import PluginRegistry, ResourceStore
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import (
    AIConfig,
    ChannelConfig,
    MCPServerConfig,
    SourceConfig,
    SourceOverride,
    SystemConfig,
    WorkflowDefinition,
)
from workflowweave.plugins.channel.email.channel import EmailChannelType
from workflowweave.plugins.channel.file.channel import FileChannelType
from workflowweave.schema import resource_options_schema, validate_instance, validate_schema
from workflowweave.workflow.execution.runner import WorkflowRunner


@pytest.fixture
async def bindings(tmp_path):
    registry = PluginRegistry(builtin_channels=[EmailChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(tmp_path / "resources.json",
                          channel_register=registry.channelRegister)
    store.save("mcp_servers", MCPServerConfig(id="server", transport="stdio", command="mcp-server"))
    store.save("sources", SourceConfig(id="source", call={
        "kind": "mcp", "server": "server", "tool": "read", "arguments": {"base": True},
    }))
    store.save("ai", AIConfig(id="ai", provider="test", models={"model": {}}))
    return store, registry


def workflow(ident="workflow", **kwargs):
    return WorkflowDefinition(id=ident, sources=["source"],
                              analyses=[{"user_prompt": "analyze input", "id": "task", "ai": "ai", "model": "model"}],
                              **kwargs)


async def test_two_workflows_share_mcp_arguments_and_keep_old_snapshots(bindings):
    store, _ = bindings
    for name in ("first", "second"):
        store.save("workflows", workflow(name, source_overrides={"source": {
            "arguments": {"records": [{"message": name}]},
            "limits": {"item_tokens": 1000},
        }}))
    first, second = store.snapshot("first"), store.snapshot("second")
    assert first.sources["source"].call.arguments == {"base": True, "records": [{"message": "first"}]}
    assert second.sources["source"].call.arguments == {"base": True, "records": [{"message": "second"}]}
    assert store.get("sources", "source").call.arguments == {"base": True}
    changed = store.get("workflows", "first")
    changed.source_overrides["source"].arguments["records"] = []
    store.save("workflows", changed)
    assert first.sources["source"].call.arguments["records"] == [{"message": "first"}]
    assert store.snapshot("first").sources["source"].call.arguments["records"] == []


async def test_cli_source_workflow_limits_override(bindings):
    store, _ = bindings
    store.save("sources", SourceConfig(
        id="source",
        call={"kind": "cli", "mode": "shell", "command": "true", "cwd": None},
    ))
    store.save("workflows", workflow(source_overrides={
        "source": {"arguments": None, "limits": {"item_tokens": 5}},
    }))

    snapshot = store.snapshot("workflow")
    assert snapshot.sources["source"].call.command == "true"
    assert snapshot.sources["source"].limits.item_tokens == 5


async def test_mcp_argument_overlay_preserves_base_and_explicit_empty_values(bindings):
    store, _ = bindings
    store.save("workflows", workflow(source_overrides={"source": {
        "arguments": {"records": []},
    }}))
    saved = store.snapshot("workflow")
    assert saved.sources["source"].call.arguments == {"base": True, "records": []}
    changed = store.get("workflows", "workflow")
    changed.source_overrides["source"].arguments = {"base": False}
    store.save("workflows", changed)
    assert store.snapshot("workflow").sources["source"].call.arguments == {"base": False}
    assert saved.sources["source"].call.arguments == {"base": True, "records": []}


async def test_detached_source_snapshot_stays_independent_from_shared_source(bindings):
    store, _ = bindings
    shared = store.get("sources", "source")
    detached = store.resolve_source("source")
    assert detached.call.arguments == {"base": True}
    store.save("workflows", workflow("linked"))
    store.save("workflows", workflow("detached", source_overrides={
        "source": {"source": detached},
    }))
    shared.enabled = False
    store.save("sources", shared)
    with pytest.raises(WorkFLowWeaveError, match="没有可用的数据源"):
        store.snapshot("linked")
    assert store.snapshot("detached").sources["source"].call.arguments == {"base": True}
    shared.enabled = True
    shared.call.arguments = {"base": False}
    store.save("sources", shared)
    assert store.snapshot("linked").sources["source"].call.arguments == {"base": False}
    assert store.snapshot("detached").sources["source"].call.arguments == {"base": True}


async def test_detached_source_snapshot_requires_its_binding_id():
    from workflowweave.models import WorkflowDefinition

    with pytest.raises(ValidationError):
        WorkflowDefinition(
            id="workflow", sources=["source"],
            analyses=[{"user_prompt": "analyze input", "id": "task", "ai": "ai", "model": "model"}],
            source_overrides={"source": {"source": {
                "id": "another", "call": {"kind": "cli", "mode": "argv", "executable": "printf"},
            }}},
        )


async def test_detached_source_uses_its_own_call_and_survives_shared_deletion(bindings):
    store, _ = bindings
    detached = SourceConfig(id="source", call=message_call("local"))
    store.save("workflows", workflow("detached", source_overrides={
        "source": {"source": detached},
    }))
    assert store.snapshot("detached").sources["source"].call.kind == "cli"
    store.delete("sources", "source")
    assert store.snapshot("detached").sources["source"].call.argv[-1] == '{"message":"local"}'
    original = detached.model_copy(deep=True)
    resolved = store.resolve_source("source", SourceOverride(source=detached))
    assert resolved.call == detached.call
    assert detached == original


async def test_email_account_can_be_saved_before_recipient_but_binding_requires_it(bindings):
    store, _ = bindings
    store.save("channels", ChannelConfig(id="account", channel="email", options={
        "host": "smtp.example.com", "port": 587, "sender": "sender@example.com",
    }))
    with pytest.raises(WorkFLowWeaveError):
        store.save("workflows", workflow(channels=["account"]))
    for name in ("first", "second"):
        store.save("workflows", workflow(name, channels=["account"], channel_overrides={
            "account": {"options": {"recipient": f"{name}@example.com"}},
        }))
        assert store.snapshot(name).channels["account"].options["recipient"] == f"{name}@example.com"
    assert "recipient" not in store.get("channels", "account").options
    before = store.get("workflows", "first")
    changed = deepcopy(before)
    changed.channel_overrides["account"].options["host"] = "other.example.com"
    with pytest.raises(WorkFLowWeaveError):
        store.save("workflows", changed)
    assert store.get("workflows", "first") == before


@pytest.mark.parametrize("overrides", [
    {"source_overrides": {"unknown": {"arguments": {}}}},
    {"channel_overrides": {"unknown": {"options": {}}}},
])
def test_overrides_must_reference_selected_ids(overrides):
    with pytest.raises(ValidationError):
        workflow(**overrides)


async def test_invalid_binding_change_is_atomic(bindings):
    store, _ = bindings
    store.save("workflows", workflow(source_overrides={"source": {"arguments": {"saved": True}}}))
    before = store.snapshot("workflow")
    changed = store.get("workflows", "workflow")
    changed.source_overrides["source"].arguments = {"invalid": float("nan")}
    with pytest.raises(WorkFLowWeaveError):
        store.save("workflows", changed)
    assert store.snapshot("workflow").sources == before.sources


async def test_mcp_snapshot_reopens_without_plugin_registry(bindings):
    store, _ = bindings
    store.save("workflows", workflow(source_overrides={"source": {"arguments": {"records": []}}}))
    reopened = ResourceStore(store.location)
    snapshot = reopened.snapshot("workflow")
    assert snapshot.sources["source"].call.arguments == {"base": True, "records": []}
    assert set(snapshot.mcp_servers) == {"server"}





@pytest.mark.parametrize("rule", [
    {"type": "string", "x-workflowweave-workflow": "true"},
    {"type": "object", "x-workflowweave-workflow": True, "x-workflowweave-credential": True},
    {"type": "object", "x-workflowweave-workflow": True,
     "properties": {"key": {"type": "object", "x-workflowweave-credential": True}}},
])
def test_invalid_scope_or_call_credentials_fail_registration_schema(rule):
    with pytest.raises(WorkFLowWeaveError):
        validate_schema({"type": "object", "properties": {"field": {
            "description": "declared option", **rule,
        }}, "additionalProperties": False})


def test_account_schema_keeps_conditional_credentials_required():
    schema = {
        "type": "object",
        "properties": {
            "user": {"type": "string", "description": "Account user"},
            "key": {"type": "object", "description": "Credential", "x-workflowweave-credential": True},
            "query": {"type": "string", "description": "Query", "x-workflowweave-workflow": True},
        },
        "required": ["query"],
        "if": {"required": ["user"]},
        "then": {"required": ["key"]},
    }
    account_schema = resource_options_schema(schema)
    validate_instance({}, account_schema)
    with pytest.raises(WorkFLowWeaveError):
        validate_instance({"user": "user"}, account_schema)
    validate_instance({"user": "user", "key": {}}, account_schema)


async def test_real_workflows_persist_distinct_inputs_and_recover_original_binding(tmp_path):
    registry = PluginRegistry(builtin_channels=[FileChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(tmp_path / "resources.json", channel_register=registry.channelRegister)
    store.save("sources", SourceConfig(id="source", call=message_call("shared")))
    store.save("ai", AIConfig(id="ai", provider="test", models={"model": {}}))
    output = tmp_path / "notifications.txt"
    store.save("channels", ChannelConfig(id="file", channel="file", options={"path": str(output)}))
    ai = AIService(channel_factories={"test": TestChannelFactory()})
    channels = ChannelManager(registry.channelRegister)
    service = WorkflowRunner(CollectorManager(None), ai, channels, store,
                             database=tmp_path / "sessions.sqlite3")
    try:
        for name in ("first", "second"):
            store.save("workflows", workflow(name, channels=["file"], source_overrides={
                "source": {"source": SourceConfig(id="source", call=message_call(name))},
            }))
            await service.trigger(name, session_id=name)
            result = await service.wait(name)
            assert result.status == "completed"
            assert result.shared_input == '[source=source; format=none]\n{"message":"' + name + '"}'
        written = output.read_text()
        assert "first" in written and "second" in written
        saved = await asyncio.to_thread(service.session_store.entry, "first", "snapshot")
        assert saved["body"]["snapshot"]["sources"]["source"]["call"]["argv"][-1] == '{"message":"first"}'
        changed = store.get("workflows", "first")
        changed.source_overrides["source"].source.call = SourceConfig(id="source", call=message_call("changed")).call
        store.save("workflows", changed)
        await service.resume("first")
        recovered = await service.wait("first")
        assert recovered.shared_input == '[source=source; format=none]\n{"message":"first"}'
        assert output.read_text() == written
    finally:
        await service.shutdown()
        await ai.close()
        await channels.stop()
