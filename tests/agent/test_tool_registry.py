import importlib
import json

from logagent.config.registry import PluginRegistry
from logagent.models import SystemConfig


async def test_builtin_tools_are_filtered_before_import_and_capture_read_only_views(tmp_path, monkeypatch):
    config = SystemConfig(plugin_dir=str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({"tool": {"agent_shell": {"enabled": False}}}))
    imports = []
    original = importlib.import_module

    def record(name, *args, **kwargs):
        imports.append(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", record)
    registry = PluginRegistry([])
    report = await registry.discover_plugins(config)
    assert not report.errors
    assert {item.name for item in registry.toolRegister.describe()} == {"mcp", "read", "write", "grep"}
    assert "logagent.agent.builtin.shell" not in imports
    read = registry.toolRegister.get("read")
    read.input_schema["properties"].clear()
    assert "path" in registry.toolRegister.get("read").input_schema["properties"]
    (tmp_path / "config.json").write_text(json.dumps({"tool": {"agent_read": {"enabled": False}}}))
    await registry.reload_plugins(config)
    assert registry.toolRegister.get("read") is None
    assert registry.toolRegister.get("shell") is not None
    assert registry.generation == 2


def external_plugin(root, owner, code):
    directory = root / owner
    directory.mkdir()
    (directory / "plugin.json").write_text(json.dumps({
        "id": owner, "version": "1", "kind": "tool", "api_version": 1,
        "entry": {"backend": "entry.py"},
    }))
    (directory / "entry.py").write_text(code)


async def test_tool_registration_rolls_back_on_name_conflict(tmp_path):
    external_plugin(tmp_path, "external", '''
from logagent.agent.builtin.declaration import ToolDeclaration, schema
async def invoke(arguments, context): return {}
class Plugin:
    def register(self, api):
        api.register_tool(ToolDeclaration("new_tool", "New", schema({}), "read", invoke))
        api.register_tool(ToolDeclaration("read", "Conflict", schema({}), "read", invoke))
plugin = Plugin()
''')
    registry = PluginRegistry([])
    report = await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path)))
    assert registry.toolRegister.get("new_tool") is None
    assert registry.toolRegister.get("read") is not None
    assert report.errors[0].details["reason"] == "registration_conflict"


async def test_external_plugin_cannot_override_disabled_builtin_id(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"tool": {"agent_read": {"enabled": False}}}))
    external_plugin(tmp_path, "agent_read", 'raise RuntimeError("must not import")')
    registry = PluginRegistry([])
    report = await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path)))
    assert report.errors[0].details["reason"] == "plugin_id_conflict"
    assert registry.toolRegister.get("read") is None


async def test_collectors_default_to_exclusive_unless_declared():
    from logagent.collection.mock import MockCollector
    from logagent.config.views import CollectorRegister, collector_registration

    class Undeclared:
        name = "legacy"
        description = "Unspecified side effects"
        options_schema = {"type": "object", "properties": {}}
        setters_schema = {"type": "object", "properties": {}}
        count_unit = "items"

        async def collect(self, options, setters, context):
            raise AssertionError("discovery cannot collect")

    view = CollectorRegister({
        "legacy": collector_registration(Undeclared(), "legacy"),
        "mock": collector_registration(MockCollector(), "builtin"),
    })
    assert {item.name: item.execution for item in view.describe()} == {
        "legacy": "exclusive", "mock": "read",
    }
