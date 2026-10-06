"""Explicit normalization for WorkFLowWeave and QwenPaw plugin manifests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import PluginKind

SOURCE_CAPABILITY_IDS = (
    "qwenpaw_memos",
    "qwenpaw_flomo",
    "qwenpaw_halo",
    "qwenpaw_karakeep",
    "qwenpaw_siyuan",
    "qwenpaw_tencent_docs",
    "qwenpaw_activity",
    "qwenpaw_codex",
    "qwenpaw_claude",
    "qwenpaw_dida",
)
_PLUGIN_KINDS = frozenset(("collector", "channel", "tool"))


@dataclass(frozen=True, slots=True)
class NormalizedPluginManifest:
    """The small, format-independent manifest consumed by discovery."""

    id: str
    display_name: str
    version: str
    kind: PluginKind
    entry_backend: str
    source_format: str
    dependencies: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


def _invalid(reason: str) -> WorkFLowWeaveError:
    return WorkFLowWeaveError("plugin_manifest_invalid", "插件清单不符合兼容契约", {"reason": reason})


def _required_string(value: Any, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise _invalid(f"{field}_invalid")
    return value


def _identifier(value: Any, field: str) -> str:
    value = _required_string(value, field)
    if len(value) > 80 or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in value):
        raise _invalid(f"{field}_invalid")
    return value


def _entry_backend(value: Any) -> str:
    if not isinstance(value, Mapping):
        raise _invalid("entry_invalid")
    backend = _required_string(value.get("backend"), "entry_backend")
    path = Path(backend)
    if (
        path.is_absolute()
        or PureWindowsPath(backend).is_absolute()
        or path.suffix != ".py"
        or any(part == ".." for part in path.parts)
        or path == Path(".")
    ):
        raise _invalid("entry_backend_invalid")
    return backend


def _dependencies(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _invalid("dependencies_invalid")
    values = tuple(_required_string(item, "dependency") for item in value)
    if len(values) != len(set(values)):
        raise _invalid("dependencies_duplicate")
    return values


def normalize_plugin_manifest(raw: Mapping[str, Any], *, directory_name: str) -> NormalizedPluginManifest:
    """Normalize a supported manifest without guessing missing semantics."""

    if not isinstance(raw, Mapping):
        raise _invalid("root_invalid")
    _identifier(directory_name, "directory")
    plugin_id = _identifier(raw.get("id"), "id")
    version = _required_string(raw.get("version"), "version")

    raw_kind = raw.get("kind")
    raw_type = raw.get("type")
    if raw_kind is not None and raw_type is not None and raw_kind != raw_type:
        raise _invalid("kind_type_conflict")
    kind = raw_kind if raw_kind is not None else raw_type
    if kind not in _PLUGIN_KINDS:
        raise _invalid("kind_invalid")

    if "api_version" in raw and raw.get("api_version") != 1:
        raise _invalid("api_version_unsupported")
    source_format = "qwenpaw" if raw_type is not None and raw.get("api_version") is None else "workflowweave-v1"
    if source_format == "workflowweave-v1" and raw_kind is None:
        raise _invalid("api_version_missing")
    allowed = (
        {"id", "version", "kind", "api_version", "entry"}
        if source_format == "workflowweave-v1"
        else {
            "id", "name", "version", "type", "description", "description_i18n",
            "author", "entry", "dependencies", "qwenpaw_version", "meta",
        }
    )
    if set(raw) - allowed:
        raise _invalid("unknown_field")
    backend = _entry_backend(raw.get("entry"))

    display_name = raw.get("name", plugin_id)
    display_name = _required_string(display_name, "name")
    metadata = raw.get("meta", {})
    if not isinstance(metadata, Mapping):
        raise _invalid("meta_invalid")

    return NormalizedPluginManifest(
        id=plugin_id,
        display_name=display_name,
        version=version,
        kind=kind,
        entry_backend=backend,
        source_format=source_format,
        dependencies=_dependencies(raw.get("dependencies")),
        metadata=MappingProxyType(dict(metadata)),
    )


def validate_source_inventory(capability_ids: Sequence[str]) -> tuple[str, ...]:
    """Validate the exact ten-source inventory used by the QwenPaw adapter."""

    actual = tuple(capability_ids)
    if len(actual) != len(set(actual)):
        raise WorkFLowWeaveError(
            "plugin_inventory_invalid", "十个来源能力中存在重复 ID", {"actual": list(actual)}
        )
    if actual != SOURCE_CAPABILITY_IDS:
        raise WorkFLowWeaveError(
            "plugin_inventory_invalid",
            "来源能力必须包含约定的十个稳定 ID",
            {"expected": list(SOURCE_CAPABILITY_IDS), "actual": list(actual)},
        )
    return actual
