from __future__ import annotations

import json
from copy import deepcopy

import pytest

from logagent.config import ConfigurationReader, PluginRegistry, expand_source
from logagent.errors import LogAgentError
from logagent.models import (
    CollectionContext,
    CollectorOutput,
    SetterTemplate,
    SourceConfig,
    SystemConfig,
)


def object_schema(properties=None, *, required=()):
    return {
        "type": "object",
        "properties": deepcopy(properties or {}),
        "required": list(required),
        "additionalProperties": False,
    }


class SampleCollector:
    description = "A deterministic test collector"
    fields = ["message", "level"]
    count_unit = "records"
    options_schema = object_schema()
    setters_schema = object_schema()

    def __init__(self, name="sample"):
        self.name = name

    async def collect(self, options, setters, context):
        return CollectorOutput(status="success", text="original", count=1)


class ConfigurableCollector(SampleCollector):
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
    setters_schema = object_schema(
        {
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Selected fields",
            },
            "filter": {
                "type": "object",
                "description": "Equals filter",
                "additionalProperties": {"type": "string"},
            },
        }
    )


PLUGIN_SUPPORT = """from logagent.models import CollectorOutput

class SampleCollector:
    description = "Plugin test collector"
    fields = ["message"]
    count_unit = "records"
    options_schema = {
        "type": "object",
        "properties": {
            "required_value": {"type": "string", "description": "Instance value"},
            "limit": {"type": "integer", "minimum": 1, "description": "Limit", "default": 10}
        },
        "required": ["required_value"],
        "additionalProperties": False
    }
    setters_schema = {"type": "object", "additionalProperties": False}

    def __init__(self, name):
        self.name = name

    async def collect(self, options, setters, context):
        return CollectorOutput(status="success", text=self.name, count=1)
"""


def write_plugin(
    root, directory, *, plugin_id=None, body=None, kind="collector", backend="main.py"
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
                "from .support import SampleCollector\n"
                "class Plugin:\n"
                "    def register(self, api):\n"
                f"        api.register_collector(SampleCollector({directory!r}))\n"
                "plugin = Plugin()\n"
            ),
            encoding="utf-8",
        )
    return package


async def discover(root, *, builtins=()):
    registry = PluginRegistry(builtin_collectors=builtins)
    report = await registry.discover_plugins(SystemConfig(plugin_dir=str(root)))
    return registry, report


async def test_system_paths_are_relative_to_config_and_defaults_are_fixed(tmp_path, monkeypatch):
    directory = tmp_path / "configuration"
    directory.mkdir()
    location = directory / "system.json"
    location.write_text(json.dumps({"plugin_dir": "../extensions", "log_file": "logs/tool.jsonl"}))
    monkeypatch.chdir(tmp_path)
    config = await ConfigurationReader().load_system(location)
    assert config.data_dir == str(directory / "data")
    assert config.plugin_dir == str(tmp_path / "extensions")
    assert config.log_file == str(directory / "logs/tool.jsonl")
    assert config.master_key_file == str(directory / "master.key")
    assert config.host == "127.0.0.1"


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        '{"port": "8000"}',
        '{"port": true}',
        '{"unknown": "secret-value"}',
        '{"port": 8000, "port": 9000}',
        '{"data_dir": ""}',
    ],
)
async def test_invalid_system_config_is_rejected_without_exposing_input(tmp_path, content):
    path = tmp_path / "system.json"
    path.write_text(content)
    with pytest.raises(LogAgentError) as error:
        await ConfigurationReader().load_system(path)
    assert "secret-value" not in error.value.info.model_dump_json()


async def test_optional_plugin_settings_are_missing_only_not_invalid_or_unreadable(tmp_path):
    reader = ConfigurationReader()
    path = tmp_path / "config.json"
    assert await reader.load_plugin_config(path) == {}
    with pytest.raises(LogAgentError, match="不存在"):
        await reader.load_system(path)
    path.write_text('{"collector": {"demo": {"enabled": "false"}}}')
    with pytest.raises(LogAgentError):
        await reader.load_plugin_config(path)
    path.unlink()
    path.mkdir()
    with pytest.raises(LogAgentError):
        await reader.load_plugin_config(path)


async def test_valid_plugin_config_and_invalid_top_level_kind(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"collector": {"demo": {"enabled": false, "defaults": {}}}}')
    config = await ConfigurationReader().load_plugin_config(path)
    assert config["collector"]["demo"].enabled is False
    path.write_text('{"unsupported": {}}')
    with pytest.raises(LogAgentError):
        await ConfigurationReader().load_plugin_config(path)


async def test_builtin_views_and_captured_implementation_are_isolated(tmp_path):
    original = ConfigurableCollector()
    registry, report = await discover(tmp_path / "missing", builtins=[original])
    assert report.errors == []
    view = registry.collectorRegister
    exposed = view.get("sample")
    assert view.get("absent") is None
    exposed.fields.clear()
    exposed.options_schema["properties"].clear()
    exposed.setters_schema["properties"].clear()
    report.registered[0].fields.clear()
    described = view.describe()
    described[0].options_schema.clear()
    described.clear()

    async def replacement(options, setters, context):
        raise AssertionError("The stable original implementation must be called")

    original.collect = replacement
    original.options_schema = object_schema()
    assert view.get("sample").fields == ["message", "level"]
    assert "limit" in view.get("sample").options_schema["properties"]
    result = await exposed.collect({}, {}, CollectionContext("workflow", "session"))
    assert result.text == "original"
    assert not hasattr(view, "register_collector")


@pytest.mark.parametrize("invalid", ["sync", "signature", "name", "fields", "schema", "default"])
async def test_invalid_builtin_declarations_prevent_publication(tmp_path, invalid):
    collector = SampleCollector()
    if invalid == "sync":
        collector.collect = lambda options, setters, context: None
    elif invalid == "signature":

        async def wrong_signature(options):
            pass

        collector.collect = wrong_signature
    elif invalid == "name":
        collector.name = "../outside"
    elif invalid == "fields":
        collector.fields = ["message", "message"]
    elif invalid == "schema":
        collector.options_schema = {"type": "array"}
    else:
        collector.options_schema = object_schema(
            {"limit": {"type": "integer", "default": "invalid", "description": "Limit"}}
        )
    registry = PluginRegistry(builtin_collectors=[collector])
    with pytest.raises(LogAgentError) as error:
        await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path)))
    assert error.value.code == "builtin_registration_failed"
    assert registry.collectorRegister.describe() == []


def test_source_expansion_order_shallow_override_and_empty_list(tmp_path):
    collector = ConfigurableCollector()
    template = SetterTemplate(
        id="template", collector="sample", setters={"fields": ["message"], "filter": {"a": "old"}}
    )
    source = SourceConfig(
        id="source",
        collector="sample",
        template="template",
        options={"required_value": "value", "connection": {"host": "instance"}},
        setters={"fields": [], "filter": {"b": "new"}},
    )
    defaults = {"limit": 7, "connection": {"host": "plugin", "label": "plugin"}}
    expanded = expand_source(
        source, collector=collector, template=template, options_defaults=defaults
    )
    assert expanded.options == {
        "required_value": "value",
        "limit": 7,
        "connection": {"host": "instance"},
    }
    assert expanded.setters == {"fields": [], "filter": {"b": "new"}}
    assert expanded.template is None
    assert expand_source(expanded, collector=collector) == expanded
    expanded.options["connection"]["host"] = "changed"
    assert source.options["connection"]["host"] == "instance"
    assert defaults["connection"]["host"] == "plugin"
    assert template.setters["fields"] == ["message"]


def test_template_missing_mismatched_or_unknown_setter_rejected():
    collector = ConfigurableCollector()
    source = SourceConfig(
        id="source", collector="sample", template="wanted", options={"required_value": "value"}
    )
    with pytest.raises(LogAgentError) as error:
        expand_source(source, collector=collector)
    assert error.value.code == "template_missing"
    for template in (
        SetterTemplate(id="other", collector="sample"),
        SetterTemplate(id="wanted", collector="other"),
        SetterTemplate(id="wanted", collector="sample", setters={"unknown": []}),
    ):
        with pytest.raises(LogAgentError):
            expand_source(source, collector=collector, template=template)


@pytest.mark.parametrize("defaults", [{"unknown": "secret"}, {"connection": {"label": "no host"}}])
def test_partial_defaults_still_validate_declared_fields_and_nested_requirements(defaults):
    with pytest.raises(LogAgentError) as error:
        expand_source(
            SourceConfig(id="source", collector="sample", options={"required_value": "yes"}),
            collector=ConfigurableCollector(),
            options_defaults=defaults,
        )
    assert "secret" not in error.value.info.model_dump_json()


async def test_semantic_validation_is_captured_and_receives_copies(tmp_path):
    collector = ConfigurableCollector()
    calls = []

    def check(options, setters):
        calls.append(options["required_value"])
        options.clear()
        setters.clear()

    collector.validate = check
    registry, _ = await discover(tmp_path, builtins=[collector])
    registered = registry.collectorRegister.get("sample")
    collector.validate = lambda options, setters: (_ for _ in ()).throw(AssertionError("replaced"))
    source = SourceConfig(id="source", collector="sample", options={"required_value": "ok"})
    expanded = expand_source(source, collector=registered)
    registered.validate(source.options, source.setters)
    assert calls == ["ok", "ok"]
    assert expanded.options["required_value"] == source.options["required_value"] == "ok"


async def test_multiple_capabilities_and_package_relative_import(tmp_path):
    write_plugin(
        tmp_path,
        "demo",
        backend="nested/main.py",
        body="""from ..support import SampleCollector
class Plugin:
    def register(self, api):
        api.register_collector(SampleCollector("first"))
        api.register_collector(SampleCollector("second"))
plugin = Plugin()
""",
    )
    registry, report = await discover(tmp_path)
    assert [item.name for item in report.registered] == ["first", "second"]
    assert all(item.plugin == "demo" for item in report.registered)
    result = await registry.collectorRegister.get("second").collect(
        {}, {}, CollectionContext("workflow", "session")
    )
    assert result.text == "second"


async def test_package_initializer_can_be_the_backend(tmp_path):
    write_plugin(tmp_path, "demo", backend="__init__.py")
    registry, report = await discover(tmp_path)
    assert not report.errors
    assert registry.collectorRegister.get("demo") is not None


async def test_initializer_importing_backend_does_not_execute_it_twice(tmp_path):
    marker = tmp_path / "imports.txt"
    package = write_plugin(
        tmp_path,
        "demo",
        body=f"""from pathlib import Path
from .support import SampleCollector
with Path({str(marker)!r}).open("a") as log:
    log.write("imported\\n")
class Plugin:
    def register(self, api):
        api.register_collector(SampleCollector("demo"))
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


@pytest.mark.parametrize("mode", ["async", "wrong_signature", "not_callable"])
async def test_invalid_optional_semantic_hooks_reject_declaration(tmp_path, mode):
    collector = SampleCollector()
    if mode == "async":

        async def validator(options, setters):
            pass

        collector.validate = validator
    elif mode == "wrong_signature":
        collector.validate = lambda options: None
    else:
        collector.validate = 5
    with pytest.raises(LogAgentError) as error:
        await discover(tmp_path, builtins=[collector])
    assert error.value.code == "builtin_registration_failed"


def test_semantic_hook_error_does_not_expose_secret_or_mutate_source():
    collector = SampleCollector()

    def validator(options, setters):
        options["modified"] = True
        raise RuntimeError("credential-super-secret")

    collector.validate = validator
    source = SourceConfig(id="source", collector="sample")
    with pytest.raises(LogAgentError) as error:
        expand_source(source, collector=collector)
    assert source.options == {}
    assert "credential-super-secret" not in error.value.info.model_dump_json()


async def test_builtin_conflict_discards_every_capability_of_plugin(tmp_path):
    write_plugin(
        tmp_path,
        "bad",
        body="""from .support import SampleCollector
class Plugin:
    def register(self, api):
        api.register_collector(SampleCollector("orphan"))
        api.register_collector(SampleCollector("sample"))
plugin = Plugin()
""",
    )
    write_plugin(tmp_path, "good")
    registry, report = await discover(tmp_path, builtins=[SampleCollector()])
    assert [item.name for item in report.registered] == ["sample", "good"]
    assert registry.collectorRegister.get("orphan") is None
    assert registry.collectorRegister.get("sample").description == SampleCollector.description
    errors = registry.collectorRegister.diagnostics("orphan")
    assert errors[0].details["reason"] == "registration_conflict"
    errors[0].details.clear()
    assert registry.collectorRegister.diagnostics("orphan")[0].details["plugin"] == "bad"


async def test_plugin_cannot_swallow_declaration_failure_and_publish_partial_state(tmp_path):
    write_plugin(
        tmp_path,
        "bad",
        body="""from .support import SampleCollector
class Plugin:
    def register(self, api):
        api.register_collector(SampleCollector("same"))
        try:
            api.register_collector(SampleCollector("same"))
        except Exception:
            pass
plugin = Plugin()
""",
    )
    registry, report = await discover(tmp_path)
    assert registry.collectorRegister.get("same") is None
    assert report.errors[0].details["reason"] == "registration_aborted"


async def test_partial_plugin_defaults_are_validated_then_expanded_only_on_request(tmp_path):
    write_plugin(tmp_path, "demo")
    (tmp_path / "config.json").write_text(
        json.dumps({"collector": {"demo": {"defaults": {"demo": {"limit": 4}}}}})
    )
    registry, report = await discover(tmp_path)
    assert not report.errors
    view = registry.collectorRegister
    defaults = view.options_defaults("demo")
    defaults["limit"] = 100
    assert view.options_defaults("demo") == {"limit": 4}
    source = expand_source(
        SourceConfig(id="source", collector="demo", options={"required_value": "instance"}),
        collector=view.get("demo"),
        options_defaults=view.options_defaults("demo"),
    )
    assert source.options["limit"] == 4
    (tmp_path / "config.json").write_text("{}")
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path)))
    assert source.options["limit"] == view.options_defaults("demo")["limit"] == 4
    assert registry.collectorRegister.options_defaults("demo") == {}


@pytest.mark.parametrize("defaults", [{"unknown": {}}, {"demo": {"not_declared": "secret-value"}}])
async def test_invalid_defaults_isolate_only_the_owning_plugin(tmp_path, defaults):
    write_plugin(tmp_path, "demo")
    write_plugin(tmp_path, "good")
    (tmp_path / "config.json").write_text(
        json.dumps({"collector": {"demo": {"defaults": defaults}}})
    )
    registry, report = await discover(tmp_path)
    assert registry.collectorRegister.get("demo") is None
    assert registry.collectorRegister.get("good") is not None
    assert "secret-value" not in report.model_dump_json()


async def test_disabled_plugin_is_not_imported(tmp_path):
    marker = tmp_path / "executed"
    write_plugin(
        tmp_path, "disabled", body=f"from pathlib import Path\nPath({str(marker)!r}).touch()"
    )
    (tmp_path / "config.json").write_text('{"collector": {"disabled": {"enabled": false}}}')
    registry, report = await discover(tmp_path)
    assert not marker.exists()
    assert report.registered == report.errors == []
    assert registry.collectorRegister.get("disabled") is None


async def test_duplicate_plugin_ids_use_stable_directory_order(tmp_path):
    write_plugin(tmp_path, "z_last", plugin_id="same")
    write_plugin(tmp_path, "a_first", plugin_id="same")
    _, report = await discover(tmp_path)
    assert [item.name for item in report.registered] == ["a_first"]
    assert report.errors[0].details["reason"] == "plugin_id_conflict"


@pytest.mark.parametrize("backend", ["../outside.py", "/tmp/outside.py", "main.txt"])
async def test_entry_must_be_a_python_file_inside_plugin(tmp_path, backend):
    package = write_plugin(tmp_path, "bad")
    manifest = json.loads((package / "plugin.json").read_text())
    manifest["entry"]["backend"] = backend
    (package / "plugin.json").write_text(json.dumps(manifest))
    (tmp_path / "outside.py").write_text("raise AssertionError('must not import')")
    _, report = await discover(tmp_path)
    assert not report.registered
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
        "from logagent.errors import LogAgentError\n"
        "class Plugin:\n"
        "    def register(self, api):\n"
        "        raise LogAgentError('custom-secret-code', 'super-secret-password', {'value': 'secret'})\n"
        "plugin = Plugin()",
        "plugin = object()",
        "class Plugin:\n    async def register(self, api):\n        pass\nplugin = Plugin()",
    ],
)
async def test_bad_entry_is_isolated_and_arbitrary_exception_data_is_redacted(tmp_path, body):
    write_plugin(tmp_path, "bad", body=body)
    write_plugin(tmp_path, "good")
    registry, report = await discover(tmp_path)
    assert registry.collectorRegister.get("good") is not None
    assert len(report.errors) == 1
    assert "super-secret-password" not in report.model_dump_json()
    assert "custom-secret-code" not in report.model_dump_json()
    assert registry.collectorRegister.diagnostics("missing")


async def test_kind_api_is_restricted_and_channel_view_is_independent(tmp_path):
    write_plugin(
        tmp_path,
        "wrong",
        body="""class Plugin:
    def register(self, api):
        api.register_channel(object())
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
    def create(self, config, credentials):
        return "stable-channel"
class Plugin:
    def register(self, api):
        api.register_channel(Channel())
plugin = Plugin()
""",
    )
    registry, report = await discover(tmp_path)
    channel = registry.channelRegister.get("mail")
    assert channel.create(None, None) == "stable-channel"
    channel.capabilities.clear()
    channel.options_schema.clear()
    assert registry.channelRegister.get("mail").capabilities == ["notification"]
    assert registry.collectorRegister.get("mail") is None
    assert len(report.errors) == 1


async def test_invalid_global_settings_leave_previous_published_view_intact(tmp_path):
    write_plugin(tmp_path, "demo")
    registry, _ = await discover(tmp_path)
    old_view = registry.collectorRegister
    (tmp_path / "config.json").write_text("not JSON")
    with pytest.raises(LogAgentError):
        await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path)))
    assert registry.collectorRegister is old_view
    assert registry.collectorRegister.get("demo") is not None
