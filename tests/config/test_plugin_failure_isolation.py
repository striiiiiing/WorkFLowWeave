"""Every optional plugin shares the same discovery transaction boundary."""

import importlib

import pytest

from tests.config.test_config import write_plugin
from workflowweave.config import PluginRegistry
from workflowweave.models import SystemConfig


@pytest.mark.parametrize("origin", ["builtin", "user"])
@pytest.mark.parametrize("kind", ["channel", "tool"])
@pytest.mark.parametrize("stage", ["manifest", "entry", "register"])
async def test_broken_plugin_does_not_remove_other_plugins(tmp_path, origin, kind, stage):
    builtin_root, user_root = tmp_path / "builtin", tmp_path / "user"
    root = builtin_root if origin == "builtin" else user_root
    write_plugin(root, "a_good")
    write_plugin(root, "z_good")
    if stage == "register" and kind == "channel":
        body = (
            "from .support import SampleChannel\n"
            "class Plugin:\n"
            "    def register(self, api):\n"
            "        api.register_channel(SampleChannel('partial'))\n"
            "        raise RuntimeError('secret-value')\n"
            "plugin = Plugin()\n"
        )
    elif stage == "register":
        body = (
            "from dataclasses import replace\n"
            "from workflowweave.agent.tools.builtin.read import plugin as read_tool\n"
            "class Plugin:\n"
            "    def register(self, api):\n"
            "        tool = replace(read_tool, name='partial')\n"
            "        api.register_tool(tool)\n"
            "        raise RuntimeError('secret-value')\n"
            "plugin = Plugin()\n"
        )
    else:
        body = "raise ImportError('secret-value')\n"
    write_plugin(root, "broken", kind=kind, body=body)
    if stage == "manifest":
        (root / "broken" / "plugin.json").write_text("invalid json", encoding="utf-8")
    registry = PluginRegistry()
    report = await registry.discover_plugins(SystemConfig(
        builtin_plugin_dir=str(builtin_root), plugin_dir=str(user_root),
    ))
    assert registry.channelRegister.get("a_good") is not None
    assert registry.channelRegister.get("z_good") is not None
    assert registry.channelRegister.get("partial") is None
    assert registry.toolRegister.get("partial") is None
    assert len(report.errors) == 1
    assert report.errors[0].details["plugin"] == "broken"
    assert report.errors[0].details["stage"] == stage
    assert "secret-value" not in report.model_dump_json()
    if stage == "register":
        assert report.errors[0].details["capabilities"] == ["partial"]


async def test_builtin_agent_tool_import_failure_is_isolated(tmp_path, monkeypatch):
    original_import = importlib.import_module

    def fail_read(name, *args, **kwargs):
        if name == "workflowweave.agent.tools.builtin.read":
            raise ImportError("secret-value")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fail_read)
    registry = PluginRegistry()
    report = await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path)))
    assert registry.toolRegister.get("read") is None
    assert registry.toolRegister.get("write") is not None
    assert registry.channelRegister.get("feishu") is not None
    assert len(report.errors) == 1
    assert report.errors[0].details["plugin"] == "agent_read"
    assert "secret-value" not in report.model_dump_json()
