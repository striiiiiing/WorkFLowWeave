"""Repository adapters must obey ordinary discovery, disable and reload semantics."""

from pathlib import Path

import pytest

from tests.fixtures.plugin_helpers import install_plugin
from workflowweave.config import PluginRegistry
from workflowweave.config import registry as registry_module
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import SystemConfig


async def test_empty_directory_does_not_register_adapter_implementations(tmp_path):
    registry = PluginRegistry()
    report = await registry.discover_plugins(SystemConfig(
        plugin_dir=str(tmp_path),
        builtin_plugin_dir=str(tmp_path.parent / f"{tmp_path.name}-builtins"),
    ))
    assert not report.errors
    assert registry.channelRegister.describe() == []


async def test_shipped_plugins_publish_real_owners_without_conflicts(installed_plugins):
    registry = PluginRegistry()
    report = await registry.discover_plugins(SystemConfig(
        plugin_dir=str(installed_plugins.parent / "user-plugins"),
    ))
    assert not report.errors
    assert {(item.kind, item.name, item.plugin) for item in report.registered
            if item.kind != "tool"} == {
        ("channel", "email", "email"),
        ("channel", "file", "file"),
        ("channel", "qq", "qq"),
        ("channel", "wechat_openclaw", "wechat_openclaw"),
        ("channel", "feishu", "feishu"),
            ("channel", "telegram", "telegram"),
    }


async def test_user_plugin_cannot_override_packaged_plugin(tmp_path):
    source = Path(__file__).parents[2] / "src/workflowweave/plugins/channel/file"
    install_plugin(source, tmp_path / "file")
    report = await PluginRegistry().discover_plugins(SystemConfig(plugin_dir=str(tmp_path)))
    assert [item.name for item in report.registered if item.kind == "channel"].count("file") == 1
    conflicts = [error for error in report.errors if error.details.get("plugin") == "file"]
    assert len(conflicts) == 1
    assert conflicts[0].details["reason"] == "plugin_id_conflict"


async def test_builtin_and_user_plugin_roots_must_be_disjoint(tmp_path):
    with pytest.raises(WorkFLowWeaveError, match="不能相同或互相包含"):
        await PluginRegistry().discover_plugins(SystemConfig(
            plugin_dir=str(tmp_path), builtin_plugin_dir=str(tmp_path / "builtins"),
        ))


async def test_disabled_adapters_are_not_imported_and_targeted_reload_retains_others(
    installed_plugins, monkeypatch,
):
    config = SystemConfig(
        plugin_dir=str(installed_plugins.parent / "user-plugins"),
        builtin_plugin_dir=str(installed_plugins),
    )
    registry = PluginRegistry()
    imported = []
    original_import = registry_module._import_entry

    def record_import(directory, entry, prefix):
        imported.append(directory.name)
        return original_import(directory, entry, prefix)

    monkeypatch.setattr(registry_module, "_import_entry", record_import)
    registry.update_plugin_setting(config, "channel", "file", False)
    registry.update_plugin_setting(config, "channel", "email", False)
    report = await registry.discover_plugins(config)
    assert not report.errors
    assert "file" not in imported and "email" not in imported
    assert registry.channelRegister.get("email") is None
    qq_factory = registry.channelRegister.get("qq").create

    registry.update_plugin_setting(config, "channel", "email", True)
    imported.clear()
    report = await registry.reload_plugins(config, owners=["email"])
    assert not report.errors
    assert imported == ["email"]
    assert registry.channelRegister.get("email") is not None
    assert registry.channelRegister.get("qq").create is qq_factory

    registry.update_plugin_setting(config, "channel", "email", False)
    imported.clear()
    report = await registry.reload_plugins(config, owners=["email"])
    assert not report.errors
    assert imported == []
    assert registry.channelRegister.get("email") is None
    assert registry.channelRegister.get("qq").create is qq_factory
