"""持久化文件渠道更名保持路径/引用且幂等，新资源不接受移除的 mock 别名。"""

from copy import deepcopy

import pytest

from workflowweave.config import PluginRegistry, ResourceStore
from workflowweave.config.migrations import migrate_legacy_snapshot, migrate_resources
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import ChannelConfig, SystemConfig


def test_file_capability_migration_preserves_identity_path_and_bindings():
    stored = {
        "format_version": 4,
        "channels": {"default_file": {"id": "default_file", "channel": "mock",
                                       "options": {"path": "existing.log"}}},
        "workflows": {"daily": {"channels": ["default_file"]}},
    }
    original = deepcopy(stored)
    migrated, changed = migrate_resources(stored)
    assert changed
    assert stored == original
    assert migrated["channels"]["default_file"] == {
        "id": "default_file", "channel": "file", "options": {"path": "existing.log"},
    }
    assert migrated["workflows"] == original["workflows"]
    assert migrate_resources(migrated) == (migrated, False)


def test_archived_snapshot_migration_does_not_mutate_input():
    snapshot = {"workflow": {}, "channels": {
        "local": {"id": "local", "channel": "mock", "options": {"path": "saved.log"}},
    }}
    original = deepcopy(snapshot)
    result = migrate_legacy_snapshot(snapshot)
    assert result["channels"]["local"]["channel"] == "file"
    assert result["channels"]["local"]["options"] == {"path": "saved.log"}
    assert snapshot == original
    assert migrate_legacy_snapshot(result) == result


async def test_new_resource_input_rejects_removed_mock_alias(tmp_path):
    registry = PluginRegistry()
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(tmp_path / "resources.json", channel_register=registry.channelRegister)
    with pytest.raises(WorkFLowWeaveError):
        store.save("channels", ChannelConfig(
            id="local", channel="mock", options={"path": "out.log"},
        ))
    assert store.list("channels") == []
