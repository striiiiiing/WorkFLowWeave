"""Disabled source resources stay available but are omitted from execution snapshots."""

import pytest

from workflowweave.config import PluginRegistry, ResourceStore
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import AIConfig, SourceConfig, SystemConfig, WorkflowDefinition


@pytest.mark.asyncio
async def test_disabled_source_is_omitted_from_workflow_snapshot(tmp_path):
    registry = PluginRegistry()
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(
        tmp_path / "resources.json",
        channel_register=registry.channelRegister,
    )
    source = SourceConfig(id="source", call={"kind": "cli", "mode": "argv", "executable": "printf"}, enabled=False)
    store.save("sources", source)
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {}}))
    store.save(
        "workflows",
        WorkflowDefinition(
            id="workflow",
            sources=[source.id],
            analyses=[{"user_prompt": "analyze input", "id": "analysis", "ai": "ai", "model": "model"}],
        ),
    )

    assert store.get("sources", source.id).enabled is False
    with pytest.raises(WorkFLowWeaveError, match="没有可用的数据源"):
        store.snapshot("workflow")
