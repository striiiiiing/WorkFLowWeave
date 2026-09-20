"""Disabled source resources stay available but are omitted from execution snapshots."""

import pytest

from logagent.channel.mock import MockFileChannelType
from logagent.collection.mock import MockCollector
from logagent.config import PluginRegistry, ResourceStore
from logagent.models import AIConfig, SourceConfig, SystemConfig, WorkflowDefinition


@pytest.mark.asyncio
async def test_disabled_source_is_omitted_from_workflow_snapshot(tmp_path):
    registry = PluginRegistry([MockCollector()], builtin_channels=[MockFileChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(
        tmp_path / "resources.json",
        collector_register=registry.collectorRegister,
        channel_register=registry.channelRegister,
    )
    source = SourceConfig(id="source", collector="mock", enabled=False)
    store.save("sources", source)
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {}}))
    store.save(
        "workflows",
        WorkflowDefinition(
            id="workflow",
            sources=[source.id],
            analyses=[{"id": "analysis", "ai": "ai", "model": "model"}],
        ),
    )

    snapshot = store.snapshot("workflow")

    assert store.get("sources", source.id).enabled is False
    assert snapshot.workflow.sources == []
    assert snapshot.sources == {}
