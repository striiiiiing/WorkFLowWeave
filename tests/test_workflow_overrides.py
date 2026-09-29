"""配置覆盖从资源绑定到采集、通知与恢复的跨模块测试。

用真实 ResourceStore、注册表和管理器验证四层配置优先级、显式空覆盖、
模板引用完整性、账户/调用字段作用域及失败提交的原子性；再经 Workflow、
SQLite 和本地文件渠道验证不同绑定相互隔离，恢复仍使用原快照。
模型使用注入的 LangChain 替身；邮件配置仅校验，不向真实收件人投递。
"""

import asyncio
from copy import deepcopy

import pytest
from pydantic import ValidationError

from logagent.ai import AIService
from logagent.channel import ChannelManager, MockFileChannelType
from logagent.channel.email import EmailChannelType
from logagent.collection import CollectorManager, MockCollector
from logagent.config import PluginRegistry, ResourceStore
from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    ChannelConfig,
    CollectionContext,
    SetterTemplate,
    SourceConfig,
    SourceOverride,
    SystemConfig,
    WorkflowDefinition,
)
from logagent.schema import resource_options_schema, validate_instance, validate_schema
from logagent.workflow.execution.runner import WorkflowRunner
from tests.workflow_ai_helpers import TestChannelFactory


@pytest.fixture
async def bindings(tmp_path):
    registry = PluginRegistry([MockCollector()], builtin_channels=[EmailChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(tmp_path / "resources.json",
                          collector_register=registry.collectorRegister,
                          channel_register=registry.channelRegister)
    store.save("sources", SourceConfig(id="source", collector="mock"))
    store.save("ai", AIConfig(id="ai", provider="test", models={"model": {}}))
    return store, registry


def workflow(ident="workflow", **kwargs):
    return WorkflowDefinition(id=ident, sources=["source"],
                              analyses=[{"id": "task", "ai": "ai", "model": "model"}],
                              **kwargs)


async def test_two_workflows_share_source_but_keep_call_options_and_old_snapshots(bindings):
    store, registry = bindings
    for name in ("first", "second"):
        store.save("workflows", workflow(name, source_overrides={"source": {
            "options": {"records": [{"message": name, "level": "INFO"}]},
            "setters": {"fields": ["message"]},
        }}))
    first, second = store.snapshot("first"), store.snapshot("second")
    manager = CollectorManager(registry.collectorRegister)
    for snapshot in (first, second):
        name = snapshot.workflow.id
        result = await manager.collect(snapshot.sources["source"], CollectionContext(name, name))
        assert result.items == [{"message": name}]
    assert store.get("sources", "source").setters == {}
    changed = store.get("workflows", "first")
    changed.source_overrides["source"].options["records"] = []
    store.save("workflows", changed)
    assert first.sources["source"].options["records"][0]["message"] == "first"
    assert store.snapshot("first").sources["source"].options["records"] == []


async def test_cli_source_workflow_limits_override_skips_collector_capability_check(bindings):
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


async def test_workflow_template_precedence_empty_override_and_reference_integrity(bindings):
    store, _ = bindings
    for name, fields in (("base", ["id"]), ("call", ["level"])):
        store.save("setters", SetterTemplate(id=name, collector="mock", setters={"fields": fields}))
    store.save("sources", SourceConfig(id="source", collector="mock", template="base",
                                       setters={"fields": ["message"]}))
    store.save("workflows", workflow(source_overrides={"source": {"template": "call"}}))
    assert store.snapshot("workflow").sources["source"].setters == {"fields": ["level"]}
    saved = store.snapshot("workflow")
    with pytest.raises(LogAgentError) as caught:
        store.delete("setters", "call")
    assert caught.value.code == "reference_conflict"
    changed = store.get("workflows", "workflow")
    changed.source_overrides["source"].setters = {"fields": []}
    store.save("workflows", changed)
    assert store.snapshot("workflow").sources["source"].setters == {"fields": []}
    assert saved.sources["source"].setters == {"fields": ["level"]}


async def test_detached_source_snapshot_stays_independent_from_shared_source(bindings):
    store, _ = bindings
    store.save("setters", SetterTemplate(id="base", collector="mock",
                                         setters={"fields": ["message"]}))
    shared = SourceConfig(
        id="source", collector="mock", template="base",
        options={"records": [{"message": "shared"}]},
    )
    store.save("sources", shared)
    detached = store.resolve_source("source")
    assert detached.template is None
    assert detached.setters == {"fields": ["message"]}

    store.save("workflows", workflow("linked"))
    store.save("workflows", workflow("detached", source_overrides={
        "source": {"source": detached},
    }))
    shared.enabled = False
    store.save("sources", shared)
    with pytest.raises(LogAgentError, match="没有可用的数据源"):
        store.snapshot("linked")
    assert store.snapshot("detached").sources["source"].options["records"] == [
        {"message": "shared"},
    ]
    shared.enabled = True
    store.save("sources", shared)
    shared.options["records"] = [{"message": "updated"}]
    store.save("sources", shared)
    assert store.snapshot("linked").sources["source"].options["records"] == [
        {"message": "updated"},
    ]
    frozen = store.snapshot("detached").sources["source"]
    assert frozen.options["records"] == [{"message": "shared"}]
    assert frozen.setters == {"fields": ["message"]}

    changed_template = store.get("setters", "base")
    changed_template.setters = {"fields": ["level"]}
    store.save("setters", changed_template)
    assert store.snapshot("detached").sources["source"].setters == {"fields": ["message"]}
    assert store.snapshot("linked").sources["source"].setters == {"fields": ["level"]}


async def test_detached_source_snapshot_requires_its_binding_id():
    from logagent.models import WorkflowDefinition

    with pytest.raises(ValidationError):
        WorkflowDefinition(
            id="workflow", sources=["source"],
            analyses=[{"id": "task", "ai": "ai", "model": "model"}],
            source_overrides={"source": {"source": {
                "id": "another", "collector": "mock",
            }}},
        )


async def test_detached_source_uses_its_own_collector_and_survives_shared_deletion(tmp_path):
    class AlternateMockCollector(MockCollector):
        name = "alternate"

    registry = PluginRegistry([MockCollector(), AlternateMockCollector()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(
        tmp_path / "resources.json", collector_register=registry.collectorRegister,
    )
    store.save("sources", SourceConfig(id="source", collector="mock"))
    store.save("ai", AIConfig(id="ai", provider="test", models={"model": {}}))
    detached = SourceConfig(
        id="source", collector="alternate", options={"records": [{"message": "local"}]},
    )
    store.save("workflows", workflow("detached", source_overrides={
        "source": {"source": detached},
    }))

    assert store.snapshot("detached").sources["source"].collector == "alternate"
    store.delete("sources", "source")
    assert store.snapshot("detached").sources["source"].options["records"] == [
        {"message": "local"},
    ]
    original = detached.model_copy(deep=True)
    resolved = store.resolve_source("source", SourceOverride(source=detached))
    assert resolved.collector == "alternate"
    assert resolved.options["records"] == [{"message": "local"}]
    assert detached == original


async def test_email_account_can_be_saved_before_recipient_but_binding_requires_it(bindings):
    store, _ = bindings
    store.save("channels", ChannelConfig(id="account", channel="email", options={
        "host": "smtp.example.com", "port": 587, "sender": "sender@example.com",
    }))
    with pytest.raises(LogAgentError):
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
    with pytest.raises(LogAgentError):
        store.save("workflows", changed)
    assert store.get("workflows", "first") == before


@pytest.mark.parametrize("overrides", [
    {"source_overrides": {"unknown": {"options": {}}}},
    {"channel_overrides": {"unknown": {"options": {}}}},
])
def test_overrides_must_reference_selected_ids(overrides):
    with pytest.raises(ValidationError):
        workflow(**overrides)


async def test_invalid_binding_and_template_change_are_atomic(bindings):
    store, _ = bindings
    store.save("setters", SetterTemplate(id="call", collector="mock", setters={"fields": ["id"]}))
    store.save("workflows", workflow(source_overrides={"source": {"template": "call"}}))
    before = store.snapshot("workflow")
    changed = store.get("workflows", "workflow")
    changed.source_overrides["source"].options = {"records": "invalid"}
    with pytest.raises(LogAgentError):
        store.save("workflows", changed)
    with pytest.raises(LogAgentError):
        store.save("setters", SetterTemplate(id="call", collector="mock", setters={"unknown": []}))
    assert store.snapshot("workflow").sources == before.sources


async def test_missing_plugin_does_not_block_saved_override_snapshot(bindings):
    store, _ = bindings
    store.save("workflows", workflow(source_overrides={"source": {"options": {"records": []}}}))
    registry = PluginRegistry([])
    empty = registry.collectorRegister
    reopened = ResourceStore(store.location, collector_register=empty)
    snapshot = reopened.snapshot("workflow")
    result = await CollectorManager(empty).collect(snapshot.sources["source"],
                                                    CollectionContext("workflow", "session"))
    assert result.status == "missing"


async def test_custom_account_requirements_call_path_and_cross_field_validation(tmp_path):
    class QueryCollector(MockCollector):
        name = "query"
        options_schema = {
            "type": "object", "additionalProperties": False,
            "properties": {
                "host": {"type": "string", "description": "Account endpoint"},
                "path": {"type": "string", "description": "Query file",
                         "x-logagent-workflow": True, "x-logagent-path": True},
                "begin": {"type": "integer", "description": "Lower bound",
                          "x-logagent-workflow": True},
                "end": {"type": "integer", "description": "Upper bound",
                        "x-logagent-workflow": True},
            },
            "required": ["host", "path", "begin", "end"],
        }

        def validate(self, options, setters):
            if options["begin"] > options["end"]:
                raise ValueError("Invalid query range")

    registry = PluginRegistry([QueryCollector()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(tmp_path / "resources.json", collector_register=registry.collectorRegister,
                          validators={"sources": CollectorManager(registry.collectorRegister).validate})
    with pytest.raises(LogAgentError):
        store.save("sources", SourceConfig(id="source", collector="query"))
    store.save("sources", SourceConfig(id="source", collector="query", options={"host": "account"}))
    store.save("ai", AIConfig(id="ai", provider="test", models={"model": {}}))
    definition = workflow(source_overrides={"source": {"options": {
        "path": "query.json", "begin": 1, "end": 2,
    }}})
    store.save("workflows", definition)
    snapshot = store.snapshot("workflow")
    assert snapshot.sources["source"].options == {
        "host": "account", "path": str(tmp_path / "query.json"), "begin": 1, "end": 2,
    }
    assert definition.source_overrides["source"].options["path"] == "query.json"
    assert store.get("workflows", "workflow").source_overrides["source"].options["path"] == str(
        tmp_path / "query.json"
    )
    definition.source_overrides["source"].options["begin"] = 3
    with pytest.raises(LogAgentError):
        store.save("workflows", definition)
    definition.source_overrides["source"].options["begin"] = 1
    definition.source_overrides["source"].options["host"] = "other-account"
    with pytest.raises(LogAgentError):
        store.save("workflows", definition)
    assert store.snapshot("workflow").sources == snapshot.sources


@pytest.mark.parametrize("rule", [
    {"type": "string", "x-logagent-workflow": "true"},
    {"type": "object", "x-logagent-workflow": True, "x-logagent-credential": True},
    {"type": "object", "x-logagent-workflow": True,
     "properties": {"key": {"type": "object", "x-logagent-credential": True}}},
])
def test_invalid_scope_or_call_credentials_fail_registration_schema(rule):
    with pytest.raises(LogAgentError):
        validate_schema({"type": "object", "properties": {"field": {
            "description": "declared option", **rule,
        }}, "additionalProperties": False})


def test_account_schema_keeps_conditional_credentials_required():
    schema = {
        "type": "object",
        "properties": {
            "user": {"type": "string", "description": "Account user"},
            "key": {"type": "object", "description": "Credential", "x-logagent-credential": True},
            "query": {"type": "string", "description": "Query", "x-logagent-workflow": True},
        },
        "required": ["query"],
        "if": {"required": ["user"]},
        "then": {"required": ["key"]},
    }
    account_schema = resource_options_schema(schema)
    validate_instance({}, account_schema)
    with pytest.raises(LogAgentError):
        validate_instance({"user": "user"}, account_schema)
    validate_instance({"user": "user", "key": {}}, account_schema)


async def test_real_workflows_persist_distinct_inputs_and_recover_original_binding(tmp_path):
    registry = PluginRegistry([MockCollector()], builtin_channels=[MockFileChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(tmp_path / "resources.json",
                          collector_register=registry.collectorRegister,
                          channel_register=registry.channelRegister)
    store.save("sources", SourceConfig(id="source", collector="mock"))
    store.save("ai", AIConfig(id="ai", provider="test", models={"model": {}}))
    output = tmp_path / "notifications.txt"
    store.save("channels", ChannelConfig(id="file", channel="mock", options={"path": str(output)}))
    ai = AIService(channel_factories={"test": TestChannelFactory()})
    channels = ChannelManager(registry.channelRegister)
    service = WorkflowRunner(CollectorManager(registry.collectorRegister), ai, channels, store,
                              database=tmp_path / "sessions.sqlite3")
    try:
        for name in ("first", "second"):
            store.save("workflows", workflow(name, channels=["file"], source_overrides={
                "source": {"options": {"records": [{"message": name}]},
                           "setters": {"fields": ["message"]}},
            }))
            await service.trigger(name, session_id=name)
            result = await service.wait(name)
            assert result.status == "completed"
            assert result.shared_input == '[source=source; format=none]\n{"message":"' + name + '"}'
        written = output.read_text()
        assert "first" in written and "second" in written
        saved = await asyncio.to_thread(service.session_store.entry, "first", "snapshot")
        assert saved["body"]["snapshot"]["sources"]["source"]["options"]["records"] == [
            {"message": "first"},
        ]
        changed = store.get("workflows", "first")
        changed.source_overrides["source"].options["records"] = [{"message": "changed"}]
        store.save("workflows", changed)
        await service.resume("first")
        recovered = await service.wait("first")
        assert recovered.shared_input == '[source=source; format=none]\n{"message":"first"}'
        assert output.read_text() == written
    finally:
        await service.shutdown()
        await ai.close()
        await channels.stop()
