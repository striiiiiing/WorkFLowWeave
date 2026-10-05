"""Repository adapters must obey ordinary discovery, disable and reload semantics."""

from logagent.config import PluginRegistry
from logagent.config import registry as registry_module
from logagent.models import SystemConfig


async def test_empty_directory_does_not_register_adapter_implementations(tmp_path):
    registry = PluginRegistry()
    report = await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path)))
    assert not report.errors
    assert registry.collectorRegister.describe() == []
    assert registry.channelRegister.describe() == []


async def test_shipped_plugins_publish_real_owners_without_conflicts(installed_plugins):
    registry = PluginRegistry()
    report = await registry.discover_plugins(SystemConfig(plugin_dir=str(installed_plugins)))
    assert not report.errors
    assert {(item.kind, item.name, item.plugin) for item in report.registered
            if item.kind != "tool"} == {
        ("collector", "mock", "mock"),
        ("collector", "logs", "logs"),
        ("collector", "history", "history"),
        ("channel", "email", "email"),
        ("channel", "mock", "mock_file"),
        ("channel", "qq", "qq"),
        ("channel", "test", "test_channel"),
    }


async def test_disabled_adapters_are_not_imported_and_targeted_reload_retains_others(
    installed_plugins, monkeypatch,
):
    config = SystemConfig(plugin_dir=str(installed_plugins))
    registry = PluginRegistry()
    imported = []
    original_import = registry_module._import_entry

    def record_import(directory, entry, prefix):
        imported.append(directory.name)
        return original_import(directory, entry, prefix)

    monkeypatch.setattr(registry_module, "_import_entry", record_import)
    registry.update_plugin_setting(config, "collector", "mock", False)
    registry.update_plugin_setting(config, "channel", "email", False)
    report = await registry.discover_plugins(config)
    assert not report.errors
    assert "mock" not in imported and "email" not in imported
    assert registry.collectorRegister.get("mock") is None
    assert registry.channelRegister.get("email") is None
    file_factory = registry.channelRegister.get("mock").create
    history_collect = registry.collectorRegister.get("history").collect

    registry.update_plugin_setting(config, "channel", "email", True)
    imported.clear()
    report = await registry.reload_plugins(config, owners=["email"])
    assert not report.errors
    assert imported == ["email"]
    assert registry.channelRegister.get("email") is not None
    assert registry.channelRegister.get("mock").create is file_factory
    assert registry.collectorRegister.get("history").collect is history_collect
    assert registry.collectorRegister.get("mock") is None

    registry.update_plugin_setting(config, "channel", "email", False)
    imported.clear()
    report = await registry.reload_plugins(config, owners=["email"])
    assert not report.errors
    assert imported == []
    assert registry.channelRegister.get("email") is None
    assert registry.channelRegister.get("mock").create is file_factory
