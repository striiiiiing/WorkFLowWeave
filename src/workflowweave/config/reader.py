"""Strict JSON settings reads with explicit, stable path interpretation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from workflowweave.errors import WorkFLowWeaveError, validation_error
from workflowweave.models import PluginConfiguration, SystemConfig

_PLUGIN_CONFIGURATION = TypeAdapter(PluginConfiguration)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON object key")
        value[key] = item
    return value


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def read_json(location: Path, *, optional: bool = False) -> Any:
    try:
        content = location.read_text(encoding="utf-8")
    except FileNotFoundError:
        if optional and not location.is_symlink():
            return {}
        raise WorkFLowWeaveError("configuration_unavailable", "配置文件不存在或无法读取") from None
    except (OSError, UnicodeError, ValueError):
        raise WorkFLowWeaveError("configuration_unavailable", "配置文件无法按 UTF-8 读取") from None
    try:
        return json.loads(
            content, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (ValueError, RecursionError):
        raise WorkFLowWeaveError("invalid_config", "配置文件不是有效且无歧义的 JSON") from None


def read_plugin_configuration(location: Path) -> PluginConfiguration:
    try:
        return _PLUGIN_CONFIGURATION.validate_python(
            read_json(location, optional=True)
        )
    except ValidationError as exc:
        raise validation_error(exc) from None


def _read_system(location: Path) -> SystemConfig:
    location = location.absolute()
    try:
        config = SystemConfig.model_validate(read_json(location))
    except ValidationError as exc:
        raise validation_error(exc) from None
    for field in ("data_dir", "plugin_dir", "master_key_file", "log_file"):
        value = getattr(config, field)
        if value is None:
            continue
        if not value:
            raise WorkFLowWeaveError("invalid_config", "系统路径不能为空", {"field": field})
        try:
            path = Path(value)
            if not path.is_absolute():
                path = location.parent / path
            setattr(config, field, str(path.resolve()))
        except (OSError, ValueError, RuntimeError):
            raise WorkFLowWeaveError("invalid_config", "系统路径无法解析", {"field": field}) from None
    return config


class ConfigurationReader:
    async def load_system(self, location: str | Path) -> SystemConfig:
        return await asyncio.to_thread(_read_system, Path(location))

    async def load_plugin_config(self, location: str | Path) -> PluginConfiguration:
        return await asyncio.to_thread(read_plugin_configuration, Path(location))
