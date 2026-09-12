"""Collector declaration, plugin discovery and file-transaction contracts."""

import json
import sys
from abc import abstractmethod
from copy import deepcopy
from textwrap import dedent, indent
from types import ModuleType

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import BaseModel, ValidationError

from logagent.collectors.base import BaseCollector
from logagent.collectors.registry import CollectorRegistry
from logagent.errors import LogAgentError
from logagent.models import Model


class Options(Model):
    limit: int = 10


class FieldsOnly(Model):
    fields: list[str] | None = None


class SampleCollector(BaseCollector):
    name = "sample"
    description = "A declared test source"
    options_model = Options
    setters_model = FieldsOnly
    fields = ("text", "level")
    count_unit = "events"

    async def collect(self, options, setters, context):
        raise AssertionError("Registration must never collect")


PLUGIN_BASE = dedent(
    """
    from logagent.collectors.base import BaseCollector, EmptyOptions, EmptySetters

    class PluginBase(BaseCollector):
        name = "template"
        description = "Temporary plugin"
        options_model = EmptyOptions
        setters_model = EmptySetters
        fields = ("text",)
        count_unit = "items"

        async def collect(self, options, setters, context):
            raise AssertionError("Discovery must never collect")

    def declare(name):
        return type("DeclaredCollector", (PluginBase,), {"name": name, "__module__": __name__})
    """
)


def write_plugin(directory, filename, body):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(PLUGIN_BASE + "\ndef register(registry):\n" + indent(dedent(body), "    "), encoding="utf-8")
    return path


def loaded_from(path):
    return {
        name: module
        for name, module in sys.modules.copy().items()
        if isinstance(module, ModuleType) and vars(module).get("__file__") == str(path)
    }


@pytest.fixture(autouse=True)
def cleanup_plugin_modules(tmp_path):
    yield
    for name, module in sys.modules.copy().items():
        if isinstance(module, ModuleType) and str(vars(module).get("__file__", "")).startswith(str(tmp_path) + "/"):
            sys.modules.pop(name, None)


def test_registry_returns_classes_and_independent_json_capability_descriptions():
    registry = CollectorRegistry()
    assert registry.register(SampleCollector) is None
    assert registry.get("sample") is SampleCollector
    assert registry.get("absent") is None
    description = registry.describe()[0]
    assert set(description) == {
        "name",
        "description",
        "options_schema",
        "setters_schema",
        "fields",
        "dynamic_fields",
        "count_unit",
        "plugin",
    }
    assert description["name"] == "sample"
    assert description["fields"] == ["text", "level"]
    assert description["count_unit"] == "events"
    assert description["plugin"] == "manual"
    assert description["dynamic_fields"] is False
    assert json.loads(json.dumps(description, allow_nan=False)) == description
    for key in ("options_schema", "setters_schema"):
        Draft202012Validator.check_schema(description[key])
    setters_schema = Draft202012Validator(description["setters_schema"])
    setters_schema.validate({"fields": ["text"]})
    with pytest.raises(SchemaValidationError):
        setters_schema.validate({"group_by": "level"})
    with pytest.raises(ValidationError):
        registry.get("sample").setters_model.model_validate({"group_by": "level"})

    original = deepcopy(description)
    description["fields"].append("external")
    description["options_schema"]["properties"]["limit"]["default"] = 999
    assert registry.describe() == [original]


def test_registration_inspects_without_constructing_or_running_hooks():
    calls = []

    class DeferredCollector(SampleCollector):
        name = "deferred"

        def __init__(self):
            calls.append("constructor")
            raise RuntimeError("Runtime construction is a Manager responsibility")

        def fields_for(self, options):
            calls.append("fields_for")
            raise AssertionError("Options are unavailable during registration")

        def count(self, items):
            calls.append("count")
            raise AssertionError("No records exist during registration")

        def format_item(self, item):
            calls.append("format_item")
            raise AssertionError("No records exist during registration")

    registry = CollectorRegistry()
    registry.register(DeferredCollector, plugin="builtin")
    assert registry.get("deferred") is DeferredCollector
    assert registry.describe()[0]["dynamic_fields"] is True
    assert registry.describe()[0]["plugin"] == "builtin"
    assert calls == []


class PermissiveModel(BaseModel):
    text: str = ""


class BrokenSchema(Model):
    @classmethod
    def model_json_schema(cls, *args, **kwargs):
        raise RuntimeError("PRIVATE_SCHEMA_CREDENTIAL")


class InvalidSchema(Model):
    @classmethod
    def model_json_schema(cls, *args, **kwargs):
        return {"type": "not_a_valid_type"}


def required_constructor(self, required):
    pass


def synchronous_collect(self, options, setters, context):
    return []


async def incomplete_collect(self, options):
    return []


async def asynchronous_hook(self, value):
    return value


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"name": "../invalid"}, "name"),
        ({"description": 7}, "description"),
        ({"options_model": dict}, "options_model"),
        ({"options_model": PermissiveModel}, "options_model"),
        ({"setters_model": PermissiveModel}, "setters_model"),
        ({"options_model": BrokenSchema}, "options_model"),
        ({"setters_model": InvalidSchema}, "setters_model"),
        ({"fields": ["text"]}, "fields"),
        ({"fields": ("text", "text")}, "fields"),
        ({"count_unit": ""}, "count_unit"),
        ({"__init__": required_constructor}, "constructor"),
        ({"collect": synchronous_collect}, "collect"),
        ({"collect": incomplete_collect}, "collect"),
        ({"count": asynchronous_hook}, "count"),
        ({"fields_for": asynchronous_hook}, "fields_for"),
        ({"format_item": asynchronous_hook}, "format_item"),
    ],
)
def test_invalid_declarations_are_rejected_without_exposing_exception_text(changes, field):
    collector = type("InvalidCollector", (SampleCollector,), changes)
    registry = CollectorRegistry()
    with pytest.raises(LogAgentError) as error:
        registry.register(collector)
    assert error.value.code == "VALIDATION_ERROR"
    assert error.value.details["errors"][0]["path"][-1] == field
    assert "PRIVATE_SCHEMA_CREDENTIAL" not in json.dumps(error.value.as_dict())
    assert registry.describe() == []


def test_registration_requires_a_concrete_class_and_never_replaces_a_name():
    class AbstractCollector(SampleCollector):
        @abstractmethod
        async def collect(self, options, setters, context):
            pass

    registry = CollectorRegistry()
    for value in (object, SampleCollector(), BaseCollector, AbstractCollector):
        with pytest.raises(LogAgentError) as error:
            registry.register(value)
        assert error.value.code == "VALIDATION_ERROR"
    registry.register(SampleCollector)
    original = registry.describe()
    duplicate = type("DuplicateCollector", (SampleCollector,), {"description": "Replacement"})
    with pytest.raises(LogAgentError) as error:
        registry.register(duplicate)
    assert error.value.code == "CONFLICT"
    assert registry.get("sample") is SampleCollector
    assert registry.describe() == original


def test_plugin_configuration_properties_are_independent_copies():
    configuration = {"nested": {"enabled": True}, "fields": ["text"]}
    registry = CollectorRegistry(configuration)
    configuration["nested"]["enabled"] = False
    exposed = registry.plugin_config
    exposed["fields"].clear()
    assert registry.plugin_config == {"nested": {"enabled": True}, "fields": ["text"]}
    assert CollectorRegistry().plugin_config == {}


@pytest.mark.parametrize("kind", ["missing", "empty", "file"])
def test_directory_diagnostics_preserve_builtins_and_are_independent(tmp_path, kind):
    path = tmp_path / "Collectors"
    if kind == "empty":
        path.mkdir()
    elif kind == "file":
        path.write_text("not a directory", encoding="utf-8")
    registry = CollectorRegistry()
    registry.register(SampleCollector, plugin="builtin")
    before = registry.describe()
    errors = registry.discover(path)
    expected = {"missing": "missing_directory", "empty": "empty_directory", "file": "invalid_directory"}
    assert len(errors) == 1
    assert errors[0].details["reason"] == expected[kind]
    assert registry.describe() == before
    errors[0].details["reason"] = "caller change"
    exposed = registry.diagnostics
    assert exposed[0].details["reason"] == expected[kind]
    exposed[0].message = "caller change"
    exposed.clear()
    assert registry.diagnostics[0].message != "caller change"


def test_discovery_shallow_merges_file_defaults_with_explicit_values(tmp_path):
    file = write_plugin(
        tmp_path,
        "configured.py",
        """
        config = registry.plugin_config
        config["nested"]["injected"] = True
        assert "injected" not in registry.plugin_config["nested"]
        collector = declare("configured")
        collector.configuration = registry.plugin_config
        registry.register(collector)
        """,
    )
    defaults = {"enabled": True, "limit": 9, "fields": ["text"], "nested": {"default": 1}, "retained": "yes"}
    file.with_suffix(".json").write_text(json.dumps(defaults), encoding="utf-8")
    overrides = {"configured": {"enabled": False, "limit": 0, "fields": [], "nested": {"override": 2}}}
    registry = CollectorRegistry({"root": "separate"})
    assert registry.discover(tmp_path, overrides) == []
    expected = {"enabled": False, "limit": 0, "fields": [], "nested": {"override": 2}, "retained": "yes"}
    assert registry.get("configured").configuration == expected
    assert registry.describe()[0]["plugin"] == "configured"
    overrides["configured"]["nested"]["override"] = "caller change"
    assert registry.get("configured").configuration == expected
    assert json.loads(file.with_suffix(".json").read_text(encoding="utf-8")) == defaults
    assert registry.plugin_config == {"root": "separate"}


def test_discovery_registers_multiple_classes_and_defaults_configuration_to_empty(tmp_path):
    file = write_plugin(
        tmp_path,
        "multiple.py",
        """
        assert registry.plugin_config == {}
        registry.register(declare("first"))
        registry.register(declare("second"))
        """,
    )
    registry = CollectorRegistry()
    assert registry.discover(tmp_path) == []
    assert [item["name"] for item in registry.describe()] == ["first", "second"]
    assert {item["plugin"] for item in registry.describe()} == {"multiple"}
    assert registry.get("first").__module__ == registry.get("second").__module__
    assert list(loaded_from(file)) == [registry.get("first").__module__]


@pytest.mark.parametrize(
    "failure",
    [
        'raise RuntimeError("PRIVATE_PLUGIN_CREDENTIAL")',
        'registry.register(declare("sample"))',
        'registry.register(declare("staged"))',
        'registry.register(type("Broken", (PluginBase,), {"name": "broken", "options_model": dict}))',
        'try:\n    registry.register(declare("sample"))\nexcept Exception:\n    pass',
    ],
    ids=["entrypoint", "builtin-conflict", "same-file-conflict", "invalid-declaration", "swallowed-conflict"],
)
def test_file_registration_is_atomic_and_other_files_still_load(tmp_path, failure):
    bad = write_plugin(tmp_path, "a_bad.py", 'registry.register(declare("staged"))\n' + failure + "\n")
    good = write_plugin(tmp_path, "z_good.py", 'registry.register(declare("good"))\n')
    registry = CollectorRegistry()
    registry.register(SampleCollector, plugin="builtin")
    errors = registry.discover(tmp_path)
    assert len(errors) == 1
    assert errors[0].details == {"reason": "registration_failed", "plugin": "a_bad.py"}
    assert "PRIVATE_PLUGIN_CREDENTIAL" not in errors[0].model_dump_json()
    assert registry.get("sample") is SampleCollector
    assert registry.get("staged") is None
    assert registry.get("broken") is None
    assert registry.get("good") is not None
    assert loaded_from(bad) == {}
    assert loaded_from(good)


def test_file_order_decides_cross_file_conflicts_without_partial_commit(tmp_path):
    write_plugin(
        tmp_path,
        "b_loser.py",
        'registry.register(declare("loser_only"))\nregistry.register(declare("shared"))\n',
    )
    winner = write_plugin(tmp_path, "a_winner.py", 'registry.register(declare("shared"))\n')
    write_plugin(tmp_path, "z_after.py", 'registry.register(declare("after"))\n')
    registry = CollectorRegistry()
    errors = registry.discover(tmp_path)
    assert len(errors) == 1
    assert errors[0].details["plugin"] == "b_loser.py"
    assert [item["name"] for item in registry.describe()] == ["shared", "after"]
    assert registry.get("loser_only") is None
    assert registry.get("shared").__module__ in loaded_from(winner)


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ('raise RuntimeError("PRIVATE_IMPORT_CREDENTIAL")\n', "import_failed"),
        ("this is invalid Python !!!!\n", "import_failed"),
        ("value = 1\n", "invalid_entrypoint"),
        ("register = 7\n", "invalid_entrypoint"),
        ("def register(registry, config):\n    pass\n", "invalid_entrypoint"),
        ("async def register(registry):\n    pass\n", "invalid_entrypoint"),
        ("def register(registry):\n    yield None\n", "invalid_entrypoint"),
    ],
)
def test_import_and_entrypoint_failures_are_isolated_and_cleanup_modules(tmp_path, source, reason):
    bad = tmp_path / "a_bad.py"
    bad.write_text(PLUGIN_BASE + "\n" + source, encoding="utf-8")
    write_plugin(tmp_path, "z_good.py", 'registry.register(declare("good"))\n')
    registry = CollectorRegistry()
    errors = registry.discover(tmp_path)
    assert len(errors) == 1
    assert errors[0].details == {"reason": reason, "plugin": "a_bad.py"}
    assert "PRIVATE_IMPORT_CREDENTIAL" not in errors[0].model_dump_json()
    assert loaded_from(bad) == {}
    assert registry.get("good") is not None


@pytest.mark.parametrize("kind", ["syntax", "non-object", "non-finite", "override-type", "override-non-finite"])
def test_bad_configuration_rejects_only_its_file_before_import(tmp_path, kind):
    bad = tmp_path / "a_bad.py"
    bad.write_text('raise RuntimeError("PRIVATE_CONFIG_CREDENTIAL")\n', encoding="utf-8")
    overrides = None
    invalid_json = {
        "syntax": '{"secret": "PRIVATE_CONFIG_CREDENTIAL",',
        "non-object": '["PRIVATE_CONFIG_CREDENTIAL"]',
        "non-finite": '{"secret": "PRIVATE_CONFIG_CREDENTIAL", "limit": NaN}',
    }
    if kind in invalid_json:
        bad.with_suffix(".json").write_text(invalid_json[kind], encoding="utf-8")
    elif kind == "override-type":
        overrides = {"a_bad": ["PRIVATE_CONFIG_CREDENTIAL"]}
    else:
        overrides = {"a_bad": {"secret": "PRIVATE_CONFIG_CREDENTIAL", "limit": float("nan")}}
    write_plugin(tmp_path, "z_good.py", 'registry.register(declare("good"))\n')
    registry = CollectorRegistry()
    errors = registry.discover(tmp_path, overrides)
    assert len(errors) == 1
    assert errors[0].details == {"reason": "invalid_config", "plugin": "a_bad.py"}
    assert "PRIVATE_CONFIG_CREDENTIAL" not in errors[0].model_dump_json()
    assert loaded_from(bad) == {}
    assert registry.get("good") is not None


def test_module_names_use_paths_and_do_not_replace_an_unrelated_module(tmp_path, monkeypatch):
    unrelated = ModuleType("custom")
    monkeypatch.setitem(sys.modules, "custom", unrelated)
    first = write_plugin(tmp_path / "one", "custom.py", 'registry.register(declare("one"))\n')
    second = write_plugin(tmp_path / "two", "custom.py", 'registry.register(declare("two"))\n')
    registry = CollectorRegistry()
    assert registry.discover(first.parent) == []
    assert registry.discover(second.parent) == []
    first_name = registry.get("one").__module__
    second_name = registry.get("two").__module__
    assert first_name != second_name
    assert first_name.startswith("_") and second_name.startswith("_")
    assert first_name in loaded_from(first)
    assert second_name in loaded_from(second)
    assert sys.modules["custom"] is unrelated


def test_failed_repeat_discovery_keeps_previously_committed_module_and_classes(tmp_path):
    file = write_plugin(tmp_path, "existing.py", 'registry.register(declare("existing"))\n')
    registry = CollectorRegistry()
    assert registry.discover(tmp_path) == []
    collector = registry.get("existing")
    modules = loaded_from(file)
    errors = registry.discover(tmp_path)
    assert len(errors) == 1
    assert registry.get("existing") is collector
    assert loaded_from(file) == modules
    assert len(registry.diagnostics) == 1
