"""Collector declarations and atomic, per-file plugin discovery."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel

from logagent._io import read_json
from logagent.collectors.base import BaseCollector
from logagent.config import validate_id
from logagent.errors import LogAgentError
from logagent.models import ErrorInfo, validate_json_value

_MODULE_PREFIX = "_logagent_collector_"


def _invalid(field: str, reason: str) -> LogAgentError:
    return LogAgentError(
        "VALIDATION_ERROR",
        "Collector declaration is invalid",
        {"errors": [{"path": ["collector", field], "reason": reason}]},
    )


def _configuration(value: Any) -> dict:
    if not isinstance(value, dict):
        raise TypeError("Plugin configuration must be a JSON object")
    validate_json_value(value)
    return deepcopy(value)


def _schema(model: Any, field: str) -> dict:
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise _invalid(field, "Declare a Pydantic model")
    if model.model_config.get("extra") != "forbid":
        raise _invalid(field, "The model must reject unknown fields")
    try:
        schema = model.model_json_schema(mode="validation")
        if not isinstance(schema, dict):
            raise TypeError("Schema must be an object")
        validate_json_value(schema)
        Draft202012Validator.check_schema(schema)
        return deepcopy(schema)
    except Exception:  # noqa: BLE001 - Plugin schema hooks may raise arbitrary exceptions.
        raise _invalid(field, "The model must provide a valid JSON Schema") from None


def _method(collector: type[BaseCollector], name: str, arguments: int, *, asynchronous: bool = False) -> None:
    method = getattr(collector, name, None)
    if (
        not callable(method)
        or inspect.iscoroutinefunction(method) != asynchronous
        or inspect.isasyncgenfunction(method)
    ):
        raise _invalid(name, "Declare an async method" if asynchronous else "Declare a synchronous method")
    if inspect.isgeneratorfunction(method):
        raise _invalid(name, "Generator methods are not supported")
    descriptor = inspect.getattr_static(collector, name)
    bound_to_class = isinstance(descriptor, (staticmethod, classmethod))
    try:
        inspect.signature(method).bind(*([None] * (arguments if bound_to_class else arguments + 1)))
    except (TypeError, ValueError):
        raise _invalid(name, "Method parameters do not match the Collector interface") from None


def _describe(collector: Any, plugin: str) -> dict:
    if (
        not isinstance(collector, type)
        or not issubclass(collector, BaseCollector)
        or collector is BaseCollector
        or inspect.isabstract(collector)
    ):
        raise _invalid("type", "Register a concrete BaseCollector class")
    try:
        inspect.signature(collector).bind()
    except (TypeError, ValueError):
        raise _invalid("constructor", "Collector must support construction without arguments") from None
    try:
        name = validate_id(getattr(collector, "name", None))
    except LogAgentError:
        raise _invalid("name", "Use 1–80 ASCII letters, digits, underscores or hyphens") from None
    description = getattr(collector, "description", None)
    if not isinstance(description, str):
        raise _invalid("description", "Description must be a string")
    fields = getattr(collector, "fields", None)
    if (
        not isinstance(fields, tuple)
        or any(not isinstance(field, str) or not field.strip() for field in fields)
        or len(set(fields)) != len(fields)
    ):
        raise _invalid("fields", "Fields must be a tuple of unique nonempty strings")
    count_unit = getattr(collector, "count_unit", None)
    if not isinstance(count_unit, str) or not count_unit.strip():
        raise _invalid("count_unit", "Declare a nonempty counting unit")
    if not isinstance(plugin, str) or not plugin.strip():
        raise _invalid("plugin", "Plugin attribution must be a nonempty string")
    if getattr(collector, "collect", None) is BaseCollector.collect:
        raise _invalid("collect", "Implement the async collect method")
    _method(collector, "collect", 3, asynchronous=True)
    _method(collector, "fields_for", 1)
    _method(collector, "count", 1)
    _method(collector, "format_item", 1)
    return {
        "name": name,
        "description": description,
        "options_schema": _schema(getattr(collector, "options_model", None), "options_model"),
        "setters_schema": _schema(getattr(collector, "setters_model", None), "setters_model"),
        "fields": list(fields),
        "dynamic_fields": collector.fields_for is not BaseCollector.fields_for,
        "count_unit": count_unit,
        "plugin": plugin,
    }


class CollectorRegistry:
    """A startup-only registry; plugin code is imported synchronously."""

    def __init__(self, plugin_config: dict | None = None):
        try:
            self._plugin_config = _configuration({} if plugin_config is None else plugin_config)
        except (TypeError, ValueError, RecursionError):
            raise LogAgentError("VALIDATION_ERROR", "Plugin configuration must be a JSON object") from None
        self._entries: dict[str, tuple[type[BaseCollector], dict]] = {}
        self._diagnostics: list[ErrorInfo] = []
        self._origin: str | None = None
        self._invalid_declaration = False

    @property
    def plugin_config(self) -> dict:
        return deepcopy(self._plugin_config)

    @property
    def diagnostics(self) -> list[ErrorInfo]:
        return deepcopy(self._diagnostics)

    def register(self, collector: type[BaseCollector], *, plugin: str = "manual") -> None:
        try:
            description = _describe(collector, self._origin if self._origin is not None else plugin)
            name = description["name"]
            if name in self._entries:
                raise LogAgentError("CONFLICT", "Collector name is already registered", {"name": name})
        except LogAgentError:
            self._invalid_declaration = True
            raise
        except Exception:  # noqa: BLE001 - Isolate failures while inspecting third-party declarations.
            self._invalid_declaration = True
            raise _invalid("type", "Collector declaration could not be inspected") from None
        self._entries = {**self._entries, name: (collector, description)}

    def get(self, name: str) -> type[BaseCollector] | None:
        entry = self._entries.get(name)
        return entry[0] if entry is not None else None

    def describe(self) -> list[dict]:
        return deepcopy([description for _, description in self._entries.values()])

    def _diagnostic(self, reason: str, *, plugin: str | None = None) -> ErrorInfo:
        details = {"reason": reason}
        if plugin is not None:
            details["plugin"] = plugin
        error = ErrorInfo(code="PLUGIN_DISCOVERY_ERROR", message="Collector plugin discovery failed", details=details)
        self._diagnostics.append(error)
        return deepcopy(error)

    def discover(self, path: str | Path, plugin_config: dict | None = None) -> list[ErrorInfo]:
        overrides = {} if plugin_config is None else plugin_config
        if not isinstance(overrides, dict) or any(not isinstance(key, str) for key in overrides):
            return [self._diagnostic("invalid_overrides")]
        try:
            directory = Path(path)
            if not directory.exists():
                return [self._diagnostic("missing_directory")]
            if not directory.is_dir():
                return [self._diagnostic("invalid_directory")]
            paths = sorted(entry for entry in directory.iterdir() if entry.suffix == ".py" and entry.is_file())
        except (OSError, TypeError, ValueError, RuntimeError):
            return [self._diagnostic("directory_unavailable")]
        if not paths:
            return [self._diagnostic("empty_directory")]
        errors = []
        for file in paths:
            error = self._discover_file(file, overrides)
            if error is not None:
                errors.append(error)
        return errors

    def _discover_file(self, file: Path, overrides: dict) -> ErrorInfo | None:
        try:
            try:
                defaults = read_json(file.with_suffix(".json"))
            except FileNotFoundError:
                defaults = {}
            configuration = _configuration(defaults)
            if file.stem in overrides:
                configuration.update(_configuration(overrides[file.stem]))
        except (OSError, TypeError, ValueError, RecursionError):
            return self._diagnostic("invalid_config", plugin=file.name)
        staged = CollectorRegistry(configuration)
        staged._entries = self._entries.copy()
        staged._origin = file.stem
        existing_names = set(self._entries)
        try:
            module_name = _MODULE_PREFIX + hashlib.sha256(str(file.resolve()).encode("utf-8")).hexdigest()
            spec = importlib.util.spec_from_file_location(module_name, file)
            if spec is None or spec.loader is None:
                return self._diagnostic("import_failed", plugin=file.name)
            module = importlib.util.module_from_spec(spec)
        except (ImportError, OSError, TypeError, ValueError, RuntimeError):
            return self._diagnostic("import_failed", plugin=file.name)
        previous_modules = {
            name: value
            for name, value in sys.modules.copy().items()
            if name == module_name or name.startswith(module_name + ".")
        }
        committed = False
        try:
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except (Exception, SystemExit):  # noqa: BLE001 - One broken plugin must not stop discovery.
                return self._diagnostic("import_failed", plugin=file.name)
            entrypoint = getattr(module, "register", None)
            if (
                not callable(entrypoint)
                or inspect.iscoroutinefunction(entrypoint)
                or inspect.isasyncgenfunction(entrypoint)
                or inspect.isgeneratorfunction(entrypoint)
            ):
                return self._diagnostic("invalid_entrypoint", plugin=file.name)
            try:
                inspect.signature(entrypoint).bind(staged)
            except (TypeError, ValueError):
                return self._diagnostic("invalid_entrypoint", plugin=file.name)
            try:
                result = entrypoint(staged)
                if inspect.isawaitable(result) or inspect.isgenerator(result) or inspect.isasyncgen(result):
                    if inspect.iscoroutine(result) or inspect.isgenerator(result):
                        result.close()
                    return self._diagnostic("invalid_entrypoint", plugin=file.name)
            except (Exception, SystemExit):  # noqa: BLE001 - Preserve file-level atomicity for plugin failures.
                return self._diagnostic("registration_failed", plugin=file.name)
            if staged._invalid_declaration:
                return self._diagnostic("registration_failed", plugin=file.name)
            additions = {name: entry for name, entry in staged._entries.items() if name not in existing_names}
            if additions.keys() & self._entries.keys():
                return self._diagnostic("name_conflict", plugin=file.name)
            self._entries = {**self._entries, **additions}
            committed = True
            return None
        except (Exception, SystemExit):  # noqa: BLE001 - Custom module attributes and callables are plugin code too.
            return self._diagnostic("registration_failed", plugin=file.name)
        finally:
            if not committed:
                for name in list(sys.modules):
                    if name == module_name or name.startswith(module_name + "."):
                        del sys.modules[name]
                sys.modules.update(previous_modules)
