"""The sole plugin discovery owner; publication is atomic per plugin and view."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterable, Mapping
from importlib.machinery import ModuleSpec
from pathlib import Path, PureWindowsPath
from types import ModuleType
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from logagent.config.manifest import normalize_plugin_manifest
from logagent.config.reader import read_json, read_plugin_configuration
from logagent.config.views import (
    ChannelRegister,
    CollectorRegister,
    ToolRegister,
    _ChannelRegistration,
    _CollectorRegistration,
    _ToolRegistration,
    channel_registration,
    collector_registration,
    tool_registration,
)
from logagent.errors import LogAgentError, validation_error
from logagent.models import (
    DiscoveryReport,
    ErrorInfo,
    JSONObject,
    PluginKind,
    PluginSettings,
    SystemConfig,
    copy_model,
)
from logagent.protocols import ChannelType, Collector, Tool

_Registration = _CollectorRegistration | _ChannelRegistration | _ToolRegistration
BUILTIN_TOOLS = {
    "agent_" + name: "logagent.agent.builtin." + name
    for name in ("mcp", "read", "write", "grep", "shell")
}
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_KNOWN_REASONS = frozenset(
    {
        "configuration_unavailable",
        "invalid_config",
        "invalid_schema",
        "invalid_declaration",
        "plugin_entry_invalid",
        "plugin_id_conflict",
        "registration_conflict",
        "registration_aborted",
    }
)


def _safe_name(value: Any) -> str | None:
    return value if type(value) is str and _IDENTIFIER.fullmatch(value) else None


class _RegistrationTransaction:
    def __init__(self, kind: PluginKind, owner: str, existing: Mapping[str, _Registration]):
        self.kind = kind
        self.owner = owner
        self.existing = existing
        self.pending: dict[str, _Registration] = {}
        self.names: list[str] = []
        self.failed = False
        self.closed = False

    def add(self, capability: Collector | ChannelType | Tool) -> None:
        if self.closed:
            raise LogAgentError("registration_aborted", "插件声明事务已经关闭")
        try:
            name = _safe_name(getattr(capability, "name", None))
            if name and name not in self.names:
                self.names.append(name)
            registration = {
                "collector": collector_registration,
                "channel": channel_registration,
                "tool": tool_registration,
            }[self.kind](capability, self.owner)
            name = registration.description.name
            if name in self.existing or name in self.pending:
                # 总不能赌读取顺序吧
                raise LogAgentError("registration_conflict", "能力名称已被注册，不能覆盖")
            self.pending[name] = registration
        except Exception:
            self.failed = True
            raise

    def finish(self) -> dict[str, _Registration]:
        self.closed = True
        if self.failed or not self.pending:
            raise LogAgentError("registration_aborted", "插件未提交完整有效的能力声明")
        return dict(self.pending)


class CollectorPluginApi:
    __slots__ = ("_transaction", "_config_path")

    def __init__(self, transaction: _RegistrationTransaction, config_path: Path):
        self._transaction = transaction
        self._config_path = config_path

    @property
    def config_path(self) -> Path:
        """Private JSON belongs to the plugin; the registry never reads it."""
        return self._config_path

    def register_collector(self, collector: Collector) -> None:
        self._transaction.add(collector)


class ChannelPluginApi:
    __slots__ = ("_transaction", "_config_path")

    def __init__(self, transaction: _RegistrationTransaction, config_path: Path):
        self._transaction = transaction
        self._config_path = config_path

    @property
    def config_path(self) -> Path:
        """Private JSON belongs to the plugin; the registry never reads it."""
        return self._config_path

    def register_channel(self, channel: ChannelType) -> None:
        self._transaction.add(channel)


class ToolPluginApi:
    __slots__ = ("_transaction", "_config_path")

    def __init__(self, transaction: _RegistrationTransaction, config_path: Path):
        self._transaction, self._config_path = transaction, config_path

    @property
    def config_path(self) -> Path:
        return self._config_path

    def register_tool(self, tool: Tool) -> None:
        self._transaction.add(tool)


def _register(plugin, transaction, config_path):
    api = {"collector": CollectorPluginApi, "channel": ChannelPluginApi,
           "tool": ToolPluginApi}[transaction.kind](transaction, config_path)
    register = getattr(plugin, "register", None)
    if not callable(register) or inspect.iscoroutinefunction(register):
        raise LogAgentError("invalid_declaration", "插件必须提供同步 plugin.register(api)")
    result = register(api)
    if inspect.iscoroutine(result):
        result.close()
    if result is not None:
        raise LogAgentError("invalid_declaration", "plugin.register 只提交声明并返回 None")
    return transaction.finish()


def _entry_path(directory: Path, backend: str) -> Path:
    path = Path(backend)
    if path.is_absolute() or PureWindowsPath(backend).is_absolute() or path.suffix != ".py":
        raise LogAgentError("plugin_entry_invalid", "插件入口必须为包内相对 .py 文件")
    try:
        entry = (directory / path).resolve(strict=True)
        if not entry.is_relative_to(directory.resolve()) or not entry.is_file():
            raise ValueError("Entry escapes plugin directory or is not a file")
    except (OSError, ValueError, RuntimeError):
        raise LogAgentError(
            "plugin_entry_invalid", "插件入口不存在、不可读或越出插件目录"
        ) from None
    return entry


def _remove_modules(prefix: str) -> None:
    for name in tuple(sys.modules):
        if name == prefix or name.startswith(prefix + "."):
            sys.modules.pop(name, None)


def _execute_module(name: str, path: Path, *, package: bool = False) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)] if package else None
    )
    if spec is None or spec.loader is None:
        raise LogAgentError("plugin_entry_invalid", "无法创建插件 Python 入口")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    parent_name, _, attribute = name.rpartition(".")
    parent = sys.modules.get(parent_name)
    if parent is not None:
        setattr(parent, attribute, module)
    return module


def _import_entry(directory: Path, entry: Path, prefix: str) -> ModuleType:
    """Use an isolated real package namespace, including nested relative imports."""
    importlib.invalidate_caches()
    directory = directory.resolve()
    initializer = directory / "__init__.py"
    if initializer.is_file():
        package = _execute_module(prefix, initializer, package=True)
        if entry == initializer:
            return package
    else:
        package = ModuleType(prefix)
        package.__path__ = [str(directory)]
        package.__package__ = prefix
        package.__spec__ = ModuleSpec(prefix, loader=None, is_package=True)
        package.__spec__.submodule_search_locations = [str(directory)]
        sys.modules[prefix] = package

    relative = entry.relative_to(directory)
    is_package = entry.name == "__init__.py"
    parts = relative.parts[:-1] if is_package else relative.with_suffix("").parts
    name = ".".join((prefix, *parts))
    parent = name.rpartition(".")[0]
    if parent and parent != prefix:
        importlib.import_module(parent)
    existing = sys.modules.get(name)
    if existing is not None:
        # A package initializer may already have imported its backend normally.
        return existing
    return _execute_module(name, entry, package=is_package)


def _failure(
    exc: Exception,
    *,
    plugin: str,
    kind: PluginKind | None,
    stage: str,
    names: Iterable[str] = (),
) -> ErrorInfo:
    # Plugins may throw their own LogAgentError with secrets in message/details.
    # Only static messages, validated identifiers and known error codes are kept.
    details: JSONObject = {
        "plugin": plugin,
        "stage": stage,
        "exception_type": type(exc).__name__,
        "capabilities": list(names),
    }
    if kind is not None:
        details["kind"] = kind
    if isinstance(exc, LogAgentError) and exc.code in _KNOWN_REASONS:
        details["reason"] = exc.code
    return ErrorInfo(code="plugin_discovery_failed", message="插件发现或注册失败", details=details)


class PluginRegistry:
    def __init__(
        self,
        builtin_collectors: Iterable[Collector] = (),
        *,
        builtin_channels: Iterable[ChannelType] = (),
    ) -> None:
        self._builtin_collectors = tuple(builtin_collectors)
        self._builtin_channels = tuple(builtin_channels)
        self._collector_register = CollectorRegister()
        self._channel_register = ChannelRegister()
        self._tool_register = ToolRegister()
        self.generation = 0
        self._lock = asyncio.Lock()

    @property
    def collectorRegister(self) -> CollectorRegister:
        return self._collector_register

    @property
    def channelRegister(self) -> ChannelRegister:
        return self._channel_register

    @property
    def toolRegister(self) -> ToolRegister:
        return self._tool_register

    async def discover_plugins(self, config: SystemConfig) -> DiscoveryReport:
        try:
            config = copy_model(config)
        except ValidationError as exc:
            raise validation_error(exc) from None
        async with self._lock:
            collectors, channels, tool_view, report = await asyncio.to_thread(self._discover, config)
            self._collector_register = collectors
            self._channel_register = channels
            self._tool_register = tool_view
            self.generation += 1
            return report.model_copy(deep=True)

    async def reload_plugins(
        self, config: SystemConfig, *, owners: Iterable[str] | None = None
    ) -> DiscoveryReport:
        """Reload selected plugin owners while retaining the other published owners."""
        try:
            config = copy_model(config)
        except ValidationError as exc:
            raise validation_error(exc) from None
        selected = None if owners is None else frozenset(owners)
        async with self._lock:
            collectors, channels, tool_view, report = await asyncio.to_thread(
                self._discover, config, reload_owners=selected
            )
            self._collector_register = collectors
            self._channel_register = channels
            self._tool_register = tool_view
            self.generation += 1
            return report.model_copy(deep=True)

    def update_plugin_setting(self, config: SystemConfig, kind: PluginKind,
                              plugin_id: str, enabled: bool) -> None:
        """Atomically update the registry's single persisted enabled source.

        Publication still happens only through ``reload_plugins``.  This method
        writes the same ``plugins/config.json`` consumed by discovery and does
        not keep an Agent-specific copy of plugin state.
        """
        if not _safe_name(plugin_id):
            raise LogAgentError("invalid_argument", "插件 ID 不符合格式")
        location = Path(config.plugin_dir) / "config.json"
        settings = read_plugin_configuration(location)
        candidate = {
            group: {ident: value.model_dump(mode="json") for ident, value in values.items()}
            for group, values in settings.items()
        }
        candidate.setdefault(kind, {})[plugin_id] = {"enabled": bool(enabled)}
        location.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(candidate, ensure_ascii=False, indent=2).encode("utf-8")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=location.parent, prefix=".plugins-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, location)
            temporary = None
        except OSError:
            raise LogAgentError("storage_failed", "插件配置原子保存失败") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _discover(
        self,
        config: SystemConfig,
        *,
        reload_owners: frozenset[str] | None = None,
    ) -> tuple[CollectorRegister, ChannelRegister, ToolRegister, DiscoveryReport]:
        entries: dict[PluginKind, dict[str, _Registration]] = {
            "collector": {}, "channel": {}, "tool": {},
        }
        for kind, capabilities in (("collector", self._builtin_collectors), ("channel", self._builtin_channels)):
            if not capabilities:
                continue
            transaction = _RegistrationTransaction(kind, "builtin", entries[kind])
            try:
                for capability in capabilities:
                    transaction.add(capability)
                entries[kind].update(transaction.finish())
            except Exception as exc:
                raise LogAgentError(
                    "builtin_registration_failed",
                    "内置能力声明无效，无法发布注册视图",
                    {"kind": kind, "exception_type": type(exc).__name__},
                ) from None

        # A targeted reload removes only the selected owners. Their replacement
        # is committed below as a per-owner transaction; all other published
        # registrations remain available during the rebuild.
        if reload_owners is not None:
            for kind, view in (("collector", self._collector_register),
                               ("channel", self._channel_register), ("tool", self._tool_register)):
                for name, registration in view._registrations.items():
                    owner = registration.description.plugin
                    if owner == "builtin" or owner in reload_owners:
                        continue
                    entries[kind][name] = registration

        root = Path(config.plugin_dir)
        settings = read_plugin_configuration(root / "config.json")
        tool_plugins = {owner: {"plugin": owner, "enabled": settings.get("tool", {}).get(
            owner, PluginSettings()).enabled} for owner in BUILTIN_TOOLS}
        try:
            directories = []
            for entry in sorted(root.iterdir(), key=lambda path: path.name):
                if not entry.is_dir() or entry.name.startswith((".", "__")):
                    continue
                if entry.name in ("channel", "collector", "tool") and not (entry / "plugin.json").exists():
                    directories.extend(sorted(
                        (child for child in entry.iterdir() if child.is_dir()
                         and not child.name.startswith((".", "__"))),
                        key=lambda path: path.name,
                    ))
                else:
                    directories.append(entry)
        except FileNotFoundError:
            directories = []
        except OSError:
            raise LogAgentError("configuration_unavailable", "插件目录无法读取") from None

        errors: list[ErrorInfo] = []
        owners: set[tuple[PluginKind, str]] = {
            ("collector", "builtin"), ("channel", "builtin"),
            *(("tool", owner) for owner in BUILTIN_TOOLS),
        }
        for owner, module_name in BUILTIN_TOOLS.items():
            if reload_owners is not None and owner not in reload_owners:
                continue
            if not settings.get("tool", {}).get(owner, PluginSettings()).enabled:
                continue
            transaction = _RegistrationTransaction("tool", owner, entries["tool"])
            try:
                module = importlib.import_module(module_name)
                entries["tool"].update(_register(
                    module.plugin, transaction, root / owner / "config.json",
                ))
            except Exception as exc:
                transaction.closed = True
                errors.append(_failure(exc, plugin=owner, kind="tool", stage="register",
                                       names=transaction.names))
        for directory in directories:
            kind: PluginKind | None = None
            plugin_id = _safe_name(directory.name) or "unidentified"
            transaction = None
            prefix = "_logagent_plugin_" + uuid4().hex
            stage = "manifest"
            try:
                try:
                    manifest = normalize_plugin_manifest(
                        read_json(directory / "plugin.json"), directory_name=directory.name
                    )
                except LogAgentError as exc:
                    # Keep the established public diagnostic for an unsafe entry
                    # while still validating it before any import occurs.
                    if exc.code == "plugin_manifest_invalid" and exc.details.get("reason") == "entry_backend_invalid":
                        raise LogAgentError("plugin_entry_invalid", "插件入口无效") from None
                    raise
                kind, plugin_id = manifest.kind, manifest.id
                if directory.parent != root and kind != directory.parent.name:
                    raise LogAgentError("invalid_declaration", "插件种类与分组目录不一致")
                if kind == "tool":
                    tool_plugins[plugin_id] = {"plugin": plugin_id, "enabled": settings.get(
                        "tool", {}).get(plugin_id, PluginSettings()).enabled}
                if reload_owners is not None and plugin_id not in reload_owners:
                    continue
                owner = (kind, plugin_id)
                if owner in owners:
                    raise LogAgentError("plugin_id_conflict", "同类插件 ID 已被使用")
                owners.add(owner)
                plugin_settings = settings.get(kind, {}).get(plugin_id, PluginSettings())
                if not plugin_settings.enabled:
                    continue
                stage = "entry"
                entry = _entry_path(directory, manifest.entry_backend)
                module = _import_entry(directory, entry, prefix)
                transaction = _RegistrationTransaction(kind, plugin_id, entries[kind])
                stage = "register"
                new_entries = _register(
                    getattr(module, "plugin", None), transaction, directory.resolve() / "config.json",
                )
                entries[kind].update(new_entries)
            except Exception as exc:
                if transaction is not None:
                    transaction.closed = True
                _remove_modules(prefix)
                errors.append(
                    _failure(
                        exc,
                        plugin=plugin_id,
                        kind=kind,
                        stage=stage,
                        names=transaction.names if transaction else (),
                    )
                )

        collectors = CollectorRegister(
            entries["collector"],
            errors=(error for error in errors if error.details.get("kind") in (None, "collector")),
        )
        channels = ChannelRegister(
            entries["channel"],
            errors=(error for error in errors if error.details.get("kind") in (None, "channel")),
        )
        tool_view = ToolRegister(
            entries["tool"],
            errors=(error for error in errors if error.details.get("kind") in (None, "tool")),
            plugins=tool_plugins.values(),
        )
        report = DiscoveryReport(
            registered=[*collectors.describe(), *channels.describe(), *tool_view.describe()],
            errors=errors,
        )
        return collectors, channels, tool_view, report
