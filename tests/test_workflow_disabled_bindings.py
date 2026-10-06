"""停用资源的工作流绑定保留、跳过执行，重新启用后恢复原覆盖。"""

from pathlib import Path

import pytest

from workflowweave.ai import AIService
from workflowweave.channel import ChannelManager
from workflowweave.collection import CollectorManager
from workflowweave.config import PluginRegistry, ResourceStore
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import AIConfig, ChannelConfig, SourceConfig, SystemConfig, WorkflowDefinition
from workflowweave.workflow.execution.runner import WorkflowRunner
from plugins.channel.file.channel import FileChannelType
from tests.fixtures.collectors import MockCollector
from tests.workflow_ai_helpers import TestChannelFactory


@pytest.mark.asyncio
async def test_disabled_bindings_are_preserved_and_reenabled_in_snapshot(tmp_path: Path):
    registry = PluginRegistry([MockCollector()], builtin_channels=[FileChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(
        tmp_path / "resources.json",
        collector_register=registry.collectorRegister,
        channel_register=registry.channelRegister,
    )
    source = SourceConfig(id="source", collector="mock", enabled=True)
    channel = ChannelConfig(
        id="channel", channel="file", options={"path": str(tmp_path / "out.txt")}, enabled=True
    )
    store.save("sources", source)
    store.save("channels", channel)
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {}}))
    workflow = WorkflowDefinition(
        id="workflow",
        sources=["source"],
        analyses=[{"user_prompt": "analyze input", "id": "task", "ai": "ai", "model": "model"}],
        channels=["channel"],
        source_overrides={"source": {"options": {"records": [{"message": "kept"}]}}},
        channel_overrides={"channel": {"options": {}}},
    )
    store.save("workflows", workflow)

    source.enabled = False
    channel.enabled = False
    store.save("sources", source)
    store.save("channels", channel)

    with pytest.raises(WorkFLowWeaveError, match="没有可用的数据源"):
        store.snapshot("workflow")
    saved = store.get("workflows", "workflow")
    assert saved.source_overrides["source"].options["records"] == [{"message": "kept"}]
    assert saved.channel_overrides["channel"].options == {}

    source.enabled = True
    channel.enabled = True
    store.save("sources", source)
    store.save("channels", channel)
    restored = store.snapshot("workflow")
    assert restored.workflow.sources == ["source"]
    assert restored.workflow.source_overrides["source"].options["records"] == [
        {"message": "kept"}
    ]
    assert restored.sources["source"].options["records"] == [{"message": "kept"}]
    assert restored.channels["channel"].options["path"].endswith("out.txt")


@pytest.mark.asyncio
async def test_disabled_bindings_change_real_execution_scope_and_restore(tmp_path: Path):
    registry = PluginRegistry([MockCollector()], builtin_channels=[FileChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(
        tmp_path / "resources.json",
        collector_register=registry.collectorRegister,
        channel_register=registry.channelRegister,
    )
    source = SourceConfig(
        id="source",
        collector="mock",
        options={"records": [{"message": "kept"}]},
        enabled=True,
    )
    channel = ChannelConfig(
        id="channel", channel="file", options={"path": str(tmp_path / "out.txt")}, enabled=True
    )
    store.save("sources", source)
    store.save("channels", channel)
    store.save("ai", AIConfig(id="ai", provider="test", models={"model": {}}))
    store.save(
        "workflows",
        WorkflowDefinition(
            id="workflow",
            sources=["source"],
            analyses=[{"user_prompt": "analyze input", "id": "task", "ai": "ai", "model": "model"}],
            channels=["channel"],
            source_overrides={"source": {"options": {"records": [{"message": "kept"}]}}},
            channel_overrides={"channel": {"options": {}}},
        ),
    )
    service = WorkflowRunner(
        CollectorManager(registry.collectorRegister),
        AIService(channel_factories={"test": TestChannelFactory()}),
        ChannelManager(registry.channelRegister),
        store,
        database=tmp_path / "runs.sqlite3",
    )
    try:
        await service.trigger("workflow", session_id="enabled")
        enabled = await service.wait("enabled")
        assert enabled.status == "completed"
        assert enabled.collection[0].status == "success"
        output = tmp_path / "out.txt"
        first_output = output.read_text()
        assert first_output

        source.enabled = False
        store.save("sources", source)
        with pytest.raises(WorkFLowWeaveError, match="没有可用的数据源"):
            await service.trigger("workflow", session_id="disabled-source")

        source.enabled = True
        channel.enabled = False
        store.save("sources", source)
        store.save("channels", channel)
        await service.trigger("workflow", session_id="disabled-channel")
        disabled_channel = await service.wait("disabled-channel")
        assert disabled_channel.collection[0].status == "success"
        assert disabled_channel.deliveries[0].status == "skipped"
        assert output.read_text() == first_output

        channel.enabled = True
        store.save("channels", channel)
        await service.trigger("workflow", session_id="restored")
        restored = await service.wait("restored")
        assert restored.status == "completed"
        assert restored.collection[0].status == "success"
        assert restored.deliveries[0].status == "success"
        assert len(output.read_text()) > len(first_output)
    finally:
        await service.shutdown()
