"""系统配置读取、插件发现及能力发布测试。

在临时目录生成真实插件清单、入口和私有配置，验证路径解析、默认值与
schema 校验；通过非法入口、重复声明、导入异常验证整插件回滚、
错误脱敏及已发布视图隔离。插件为测试生成，不加载用户插件或远程服务。
"""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from workflowweave.config import ConfigurationReader, PluginRegistry
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import (
    ChannelConfig,
    SystemConfig,
)


def object_schema(properties=None, *, required=()):
    return {
        "type": "object",
        "properties": deepcopy(properties or {}),
        "required": list(required),
        "additionalProperties": False,
    }


class SampleChannel:
    description = "A deterministic test channel"
    capabilities = ["notification"]
    options_schema = object_schema()

    def __init__(self, name="sample"):
        self.name = name

    async def create(self, config, credentials):
        return "original"


class ConfigurableChannel(SampleChannel):
    options_schema = object_schema(
        {
            "required_value": {"type": "string", "description": "An instance value"},
            "limit": {"type": "integer", "minimum": 1, "default": 10, "description": "Limit"},
            "connection": {
                "type": "object",
                "description": "Connection as a whole value",
                "properties": {
                    "host": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["host"],
                "additionalProperties": False,
                "default": {"host": "schema", "label": "schema"},
            },
        },
        required=["required_value"],
    )



PLUGIN_SUPPORT = """
class SampleChannel:
    description = "Plugin test channel"
    capabilities = ["notification"]
    options_schema = {
        "type": "object",
        "properties": {
            "required_value": {"type": "string", "description": "Instance value"},
            "limit": {"type": "integer", "minimum": 1, "description": "Limit", "default": 10}
        },
        "required": ["required_value"],
        "additionalProperties": False
    }

    def __init__(self, name):
        self.name = name

    async def create(self, config, credentials):
        return self.name
"""


def write_plugin(
    root, directory, *, plugin_id=None, body=None, kind="channel", backend="main.py"
):
    package = root / directory
    package.mkdir(parents=True)
    (package / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id or directory,
                "version": "1.0",
                "kind": kind,
                "api_version": 1,
                "entry": {"backend": backend},
            }
        ),
        encoding="utf-8",
    )
    (package / "support.py").write_text(PLUGIN_SUPPORT, encoding="utf-8")
    path = package / backend
    if not path.is_absolute() or path.is_relative_to(package):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            body
            or (
                "from .support import SampleChannel\n"
                "class Plugin:\n"
                "    def register(self, api):\n"
                f"        api.register_channel(SampleChannel({directory!r}))\n"
                "plugin = Plugin()\n"
            ),
            encoding="utf-8",
        )
    return package


async def discover(root, *, builtins=()):
    registry = PluginRegistry(builtin_channels=builtins)
    report = await registry.discover_plugins(SystemConfig(
        plugin_dir=str(root), builtin_plugin_dir=str(root.parent / f"{root.name}-builtins"),
    ))
    return registry, report


async def test_system_paths_are_relative_to_config_and_defaults_are_fixed(tmp_path, monkeypatch):
    directory = tmp_path / "configuration"
    directory.mkdir()
    location = directory / "system.json"
    location.write_text(json.dumps({
        "plugin_dir": "../extensions",
        "builtin_plugin_dir": "../builtin-extensions",
        "log_file": "logs/tool.jsonl",
    }))
    monkeypatch.chdir(tmp_path)
    config = await ConfigurationReader().load_system(location)
    assert config.data_dir == str(directory / "data")
    assert config.plugin_dir == str(tmp_path / "extensions")
    assert config.builtin_plugin_dir == str(tmp_path / "builtin-extensions")
    assert config.log_file == str(directory / "logs/tool.jsonl")
    assert config.master_key_file == str(directory / "master.key")
    assert config.host == "127.0.0.1"


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        '{"port": "invalid"}',
        '{"port": 65536}',
        '{"unknown": "secret-value"}',
        '{"port": 8000, "port": 9000}',
        '{"data_dir": ""}',
    ],
)
async def test_invalid_system_config_is_rejected_without_exposing_input(tmp_path, content):
    path = tmp_path / "system.json"
    path.write_text(content)
    with pytest.raises(WorkFLowWeaveError) as error:
        await ConfigurationReader().load_system(path)
    assert "secret-value" not in error.value.info.model_dump_json()


async def test_optional_plugin_settings_are_missing_only_not_invalid_or_unreadable(tmp_path):
    reader = ConfigurationReader()
    path = tmp_path / "config.json"
    assert await reader.load_plugin_config(path) == {}
    with pytest.raises(WorkFLowWeaveError, match="不存在"):
        await reader.load_system(path)
    path.write_text('{"channel": {"demo": {"enabled": "invalid"}}}')
    with pytest.raises(WorkFLowWeaveError):
        await reader.load_plugin_config(path)
    path.unlink()
    path.mkdir()
    with pytest.raises(WorkFLowWeaveError):
        await reader.load_plugin_config(path)


async def test_valid_plugin_config_and_invalid_top_level_kind(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"channel": {"demo": {"enabled": false}}}')
    config = await ConfigurationReader().load_plugin_config(path)
    assert config["channel"]["demo"].enabled is False
    path.write_text('{"unsupported": {}}')
    with pytest.raises(WorkFLowWeaveError):
        await ConfigurationReader().load_plugin_config(path)


async def test_builtin_views_and_captured_implementation_are_isolated(tmp_path):
    original = ConfigurableChannel()
    registry, report = await discover(tmp_path / "missing", builtins=[original])
    assert report.errors == []
    view = registry.channelRegister
    exposed = view.get("sample")
    assert view.get("absent") is None
    exposed.options_schema["properties"].clear()
    described = view.describe()
    described[0].options_schema.clear()
    described.clear()

    async def replacement(config, credentials):
        raise AssertionError("The stable original implementation must be called")

    original.create = replacement
    original.options_schema = object_schema()
    assert view.get("sample").capabilities == ["notification"]
    assert "limit" in view.get("sample").options_schema["properties"]
    result = await exposed.create(None, None)
    assert result == "original"
    assert not hasattr(view, "register_channel")


@pytest.mark.parametrize("invalid", ["sync", "signature", "name", "capabilities", "schema", "default"])
async def test_invalid_builtin_declarations_prevent_publication(tmp_path, invalid):
    channel = SampleChannel()
    if invalid == "sync":
        channel.create = lambda config, credentials: None
    elif invalid == "signature":

        async def wrong_signature(options):
            pass

        channel.create = wrong_signature
    elif invalid == "name":
        channel.name = "../outside"
    elif invalid == "capabilities":
            channel.capabilities = [object()]
    elif invalid == "schema":
        channel.options_schema = {"type": "array"}
    else:
        channel.options_schema = object_schema(
            {"limit": {"type": "integer", "default": "invalid", "description": "Limit"}}
        )
    registry = PluginRegistry(builtin_channels=[channel])
    with pytest.raises(WorkFLowWeaveError) as error:
        await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path)))
    assert error.value.code == "builtin_registration_failed"
    assert registry.channelRegister.describe() == []





async def test_multiple_capabilities_and_package_relative_import(tmp_path):
    write_plugin(
        tmp_path,
        "demo",
        backend="nested/main.py",
        body="""from ..support import SampleChannel
class Plugin:
    def register(self, api):
        api.register_channel(SampleChannel("first"))
        api.register_channel(SampleChannel("second"))
plugin = Plugin()
""",
    )
    registry, report = await discover(tmp_path)
    assert [item.name for item in report.registered if item.kind == "channel"] == ["first", "second"]
    assert all(item.plugin == "demo" for item in report.registered if item.kind == "channel")
    result = await registry.channelRegister.get("second").create(
        None, None
    )
    assert result == "second"


async def test_package_initializer_can_be_the_backend(tmp_path):
    write_plugin(tmp_path, "demo", backend="__init__.py")
    registry, report = await discover(tmp_path)
    assert not report.errors
    assert registry.channelRegister.get("demo") is not None


async def test_initializer_importing_backend_does_not_execute_it_twice(tmp_path):
    marker = tmp_path / "imports.txt"
    package = write_plugin(
        tmp_path,
        "demo",
        body=f"""from pathlib import Path
from .support import SampleChannel
with Path({str(marker)!r}).open("a") as log:
    log.write("imported\\n")
class Plugin:
    def register(self, api):
        api.register_channel(SampleChannel("demo"))
plugin = Plugin()
""",
    )
    (package / "__init__.py").write_text("from .main import plugin\n")
    _, report = await discover(tmp_path)
    assert not report.errors
    assert marker.read_text().splitlines() == ["imported"]


@pytest.mark.parametrize("change", [{"api_version": 2}, {"unexpected": "secret-value"}])
async def test_manifest_validation_precedes_backend_import(tmp_path, change):
    marker = tmp_path / "imported"
    package = write_plugin(
        tmp_path, "bad", body=f"from pathlib import Path\nPath({str(marker)!r}).touch()"
    )
    manifest = json.loads((package / "plugin.json").read_text())
    manifest.update(change)
    (package / "plugin.json").write_text(json.dumps(manifest))
    _, report = await discover(tmp_path)
    assert len(report.errors) == 1
    assert report.errors[0].details["stage"] == "manifest"
    assert "secret-value" not in report.model_dump_json()
    assert not marker.exists()








async def test_builtin_conflict_discards_every_capability_of_plugin(tmp_path):
    write_plugin(
        tmp_path,
        "bad",
        body="""from .support import SampleChannel
class Plugin:
    def register(self, api):
        api.register_channel(SampleChannel("orphan"))
        api.register_channel(SampleChannel("sample"))
plugin = Plugin()
""",
    )
    write_plugin(tmp_path, "good")
    registry, report = await discover(tmp_path, builtins=[SampleChannel()])
    assert [item.name for item in report.registered if item.kind == "channel"] == ["sample", "good"]
    assert registry.channelRegister.get("orphan") is None
    assert registry.channelRegister.get("sample").description == SampleChannel.description
    errors = registry.channelRegister.diagnostics("orphan")
    assert errors[0].details["reason"] == "registration_conflict"
    errors[0].details.clear()
    assert registry.channelRegister.diagnostics("orphan")[0].details["plugin"] == "bad"


async def test_plugin_cannot_swallow_declaration_failure_and_publish_partial_state(tmp_path):
    write_plugin(
        tmp_path,
        "bad",
        body="""from .support import SampleChannel
class Plugin:
    def register(self, api):
        api.register_channel(SampleChannel("same"))
        try:
            api.register_channel(SampleChannel("same"))
        except Exception:
            pass
plugin = Plugin()
""",
    )
    registry, report = await discover(tmp_path)
    assert registry.channelRegister.get("same") is None
    assert report.errors[0].details["reason"] == "registration_aborted"


@pytest.mark.parametrize("defaults", [{}, {"demo": {"limit": 4}}])
async def test_old_framework_plugin_defaults_are_explicitly_rejected(tmp_path, defaults):
    (tmp_path / "config.json").write_text(
        json.dumps({"channel": {"demo": {"defaults": defaults}}})
    )
    with pytest.raises(WorkFLowWeaveError):
        await discover(tmp_path)


async def test_plugin_reads_private_json_and_injects_constructor_dependencies(tmp_path):
    package = write_plugin(tmp_path, "private", body='''
import json
from .support import SampleChannel
from workflowweave.models import ChannelConfig

class ConfiguredChannel(SampleChannel):
    def __init__(self, prefix):
        super().__init__("private")
        self.prefix = prefix

    async def create(self, config, credentials):
        return self.prefix + config.options["required_value"]

class Plugin:
    def register(self, api):
        assert api.config_path.is_absolute()
        settings = json.loads(api.config_path.read_text())
        api.register_channel(ConfiguredChannel(settings["prefix"]))
plugin = Plugin()
''')
    private = package / "config.json"
    private.write_text('{"prefix": "original:"}')
    registry, report = await discover(tmp_path)
    assert not report.errors
    original = registry.channelRegister.get("private")
    private.write_text('{"prefix": "new:"}')
    await registry.reload_plugins(SystemConfig(plugin_dir=str(tmp_path)), owners=["private"])
    config = ChannelConfig(id="test", channel="private", options={"required_value": "value"})
    assert await original.create(config, None) == "original:value"
    current = registry.channelRegister.get("private")
    assert await current.create(config, None) == "new:value"


@pytest.mark.parametrize("private", [None, "broken JSON", '{"unexpected": 1}'])
async def test_invalid_private_configuration_rolls_back_only_its_plugin(tmp_path, private):
    package = write_plugin(tmp_path, "private", body='''
import json
from .support import SampleChannel
class Plugin:
    def register(self, api):
        api.register_channel(SampleChannel("temporary"))
        settings = json.loads(api.config_path.read_text())
        if settings["required"] != "valid":
            raise ValueError("bad private configuration")
plugin = Plugin()
''')
    if private is not None:
        (package / "config.json").write_text(private)
    write_plugin(tmp_path, "good")
    registry, report = await discover(tmp_path)
    assert len(report.errors) == 1
    assert registry.channelRegister.get("temporary") is None
    assert registry.channelRegister.get("good") is not None


async def test_disabled_plugin_is_not_imported(tmp_path):
    marker = tmp_path / "executed"
    write_plugin(
        tmp_path, "disabled", body=f"from pathlib import Path\nPath({str(marker)!r}).touch()"
    )
    (tmp_path / "config.json").write_text('{"channel": {"disabled": {"enabled": false}}}')
    registry, report = await discover(tmp_path)
    assert not marker.exists()
    assert [item for item in report.registered if item.kind == "channel"] == report.errors == []
    assert registry.channelRegister.get("disabled") is None


async def test_duplicate_plugin_ids_use_stable_directory_order(tmp_path):
    write_plugin(tmp_path, "z_last", plugin_id="same")
    write_plugin(tmp_path, "a_first", plugin_id="same")
    _, report = await discover(tmp_path)
    assert [item.name for item in report.registered if item.kind == "channel"] == ["a_first"]
    assert report.errors[0].details["reason"] == "plugin_id_conflict"


async def test_plugin_id_prefix_is_validated_and_published(tmp_path):
    write_plugin(
        tmp_path,
        "prefixed",
        body="""from workflowweave.models import ChannelConfig
class Channel:
    name = "prefixed"
    id_prefix = "logs"
    description = "Prefixed channel"
    capabilities = ["notification"]
    options_schema = {"type": "object", "additionalProperties": False}
    async def create(self, config, credentials):
        return ""
class Plugin:
    def register(self, api):
        api.register_channel(Channel())
plugin = Plugin()
""",
    )
    registry, report = await discover(tmp_path)
    assert report.registered[0].id_prefix == "logs"
    assert registry.channelRegister.describe()[0].id_prefix == "logs"


@pytest.mark.parametrize("prefix", [123, "", "has space", "x" * 44])
async def test_invalid_plugin_id_prefix_is_rejected(tmp_path, prefix):
    write_plugin(
        tmp_path,
        "invalid_prefix",
        body=f"""from workflowweave.models import ChannelConfig
class Channel:
    name = "invalid_prefix"
    id_prefix = {prefix!r}
    description = "Invalid prefix channel"
    capabilities = ["notification"]
    options_schema = {{"type": "object", "additionalProperties": False}}
    async def create(self, config, credentials):
        return ""
class Plugin:
    def register(self, api):
        api.register_channel(Channel())
plugin = Plugin()
""",
    )
    _, report = await discover(tmp_path)
    assert not [item for item in report.registered if item.kind == "channel"]
    assert report.errors[0].details["reason"] == "invalid_declaration"


@pytest.mark.parametrize("backend", ["../outside.py", "/tmp/outside.py", "main.txt"])
async def test_entry_must_be_a_python_file_inside_plugin(tmp_path, backend):
    package = write_plugin(tmp_path, "bad")
    manifest = json.loads((package / "plugin.json").read_text())
    manifest["entry"]["backend"] = backend
    (package / "plugin.json").write_text(json.dumps(manifest))
    (tmp_path / "outside.py").write_text("raise AssertionError('must not import')")
    _, report = await discover(tmp_path)
    assert not [item for item in report.registered if item.kind == "channel"]
    assert report.errors[0].details["reason"] == "plugin_entry_invalid"


async def test_entry_symlink_cannot_escape_package(tmp_path):
    package = write_plugin(tmp_path, "bad")
    outside = tmp_path / "outside.py"
    outside.write_text("raise AssertionError('must not import')")
    (package / "main.py").unlink()
    (package / "main.py").symlink_to(outside)
    _, report = await discover(tmp_path)
    assert report.errors[0].details["reason"] == "plugin_entry_invalid"


@pytest.mark.parametrize(
    "body",
    [
        "raise RuntimeError('super-secret-password')",
        "from workflowweave.errors import WorkFLowWeaveError\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        raise WorkFLowWeaveError('custom-secret-code', 'super-secret-password', {'value': 'secret'})\n"
        "plugin = Plugin()",
        "plugin = object()",
        "class Plugin:\n    async def register(self, api):\n        pass\nplugin = Plugin()",
    ],
)
async def test_bad_entry_is_isolated_and_arbitrary_exception_data_is_redacted(tmp_path, body):
    write_plugin(tmp_path, "bad", body=body)
    write_plugin(tmp_path, "good")
    registry, report = await discover(tmp_path)
    assert registry.channelRegister.get("good") is not None
    assert len(report.errors) == 1
    assert "super-secret-password" not in report.model_dump_json()
    assert "custom-secret-code" not in report.model_dump_json()
    assert registry.channelRegister.diagnostics("missing")


async def test_kind_api_is_restricted_and_channel_view_is_independent(tmp_path):
    write_plugin(
        tmp_path,
        "wrong",
        body="""class Plugin:
    def register(self, api):
        api.register_tool(object())
plugin = Plugin()
""",
    )
    write_plugin(
        tmp_path,
        "channel",
        kind="channel",
        body="""class Channel:
    name = "mail"
    description = "Test notification type"
    capabilities = ["notification"]
    options_schema = {"type": "object", "additionalProperties": False}
    async def create(self, config, credentials):
        return "stable-channel"
class Plugin:
    def register(self, api):
        api.register_channel(Channel())
plugin = Plugin()
""",
    )
    registry, report = await discover(tmp_path)
    channel = registry.channelRegister.get("mail")
    assert await channel.create(None, None) == "stable-channel"
    channel.capabilities.clear()
    channel.options_schema.clear()
    assert registry.channelRegister.get("mail").capabilities == ["notification"]
    assert registry.toolRegister.get("mail") is None
    assert len(report.errors) == 1


async def test_invalid_global_settings_leave_previous_published_view_intact(tmp_path):
    write_plugin(tmp_path, "demo")
    registry, _ = await discover(tmp_path)
    old_view = registry.channelRegister
    (tmp_path / "config.json").write_text("not JSON")
    with pytest.raises(WorkFLowWeaveError):
        await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path)))
    assert registry.channelRegister is old_view
    assert registry.channelRegister.get("demo") is not None


async def test_string_config_values_normalize_through_readers_and_store(tmp_path):
    from workflowweave.config.store import ResourceStore
    from workflowweave.plugins.channel.file.channel import FileChannelType

    system = tmp_path / "system.json"
    system.write_text('{"port": "4300"}')
    assert (await ConfigurationReader().load_system(system)).port == 4300
    plugins = tmp_path / "plugins.json"
    plugins.write_text('{"channel": {"demo": {"enabled": "false"}}}')
    config = await ConfigurationReader().load_plugin_config(plugins)
    assert config["channel"]["demo"].enabled is False
    registry = PluginRegistry(builtin_channels=[FileChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    store = ResourceStore(tmp_path / "resources.json", channel_register=registry.channelRegister)
    source = store.save("sources", {"id": "source", "call": {
        "kind": "cli", "mode": "argv", "executable": "printf", "argv": ["%s", "example"],
    }, "timeout": "2.5"})
    assert source.timeout == 2.5
    assert store.list("sources")[0].timeout == 2.5
    channel = store.save("channels", {"id": "channel", "channel": "file", "enabled": "false", "options": {"path": "out.txt"}})
    assert channel.enabled is False
    ai = store.save("ai", {"id": "ai", "provider": "mock", "models": {"mock": {}}, "retries": "3"})
    assert ai.retries == 3
