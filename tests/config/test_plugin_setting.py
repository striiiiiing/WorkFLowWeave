import json

from workflowweave.config.registry import PluginRegistry
from workflowweave.models import SystemConfig


def test_plugin_setting_update_uses_registry_config_file(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    registry = PluginRegistry()
    registry.update_plugin_setting(
        SystemConfig(plugin_dir=str(plugin_dir)), "tool", "agent_shell", False
    )
    assert json.loads((plugin_dir / "config.json").read_text())["tool"]["agent_shell"] == {
        "enabled": False
    }
