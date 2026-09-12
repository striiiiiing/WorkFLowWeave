"""JSON configuration, reference-safe resources and immutable run snapshots."""

import asyncio
import re
from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError

from logagent._io import atomic_write, json_bytes, read_json, run_io
from logagent.errors import LogAgentError
from logagent.models import (
    RESOURCE_MODELS,
    Model,
    SystemConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
    validate_json_value,
)


def validation_error(exc: ValidationError, *, prefix=()) -> LogAgentError:
    errors = [
        {"path": list(prefix) + list(error["loc"]), "reason": error["msg"]}
        for error in exc.errors(include_url=False, include_context=False, include_input=False)
    ]
    return LogAgentError("VALIDATION_ERROR", "Configuration is invalid", {"errors": errors})


def validate_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise LogAgentError("VALIDATION_ERROR", "ID must be 1–80 ASCII letters, digits, underscores or hyphens")
    return value


def _resolve_path(path: Path, *, field: tuple[str, ...]) -> Path:
    try:
        return path.resolve()
    except (ValueError, RuntimeError) as exc:
        raise LogAgentError(
            "VALIDATION_ERROR",
            "Configuration path is invalid",
            {"errors": [{"path": list(field), "reason": "Path cannot be resolved"}]},
        ) from exc
    except OSError as exc:
        raise LogAgentError("CONFIG_UNAVAILABLE", "Cannot resolve configuration path", {"path": list(field)}) from exc


def _load_system_config(path: Path) -> SystemConfig:
    path = _resolve_path(path, field=("config",))
    try:
        config = SystemConfig.model_validate(read_json(path))
    except FileNotFoundError as exc:
        raise LogAgentError("CONFIG_NOT_FOUND", "System configuration file does not exist") from exc
    except ValidationError as exc:
        raise validation_error(exc) from exc
    except ValueError as exc:
        raise LogAgentError("CONFIG_INVALID_JSON", "System configuration is not valid JSON") from exc
    except OSError as exc:
        raise LogAgentError("CONFIG_UNAVAILABLE", "Cannot read system configuration") from exc
    base = path.parent
    config._base_dir = base
    config.data_dir = _resolve_path(base / config.data_dir, field=("data_dir",))
    config.plugin_dir = _resolve_path(base / config.plugin_dir, field=("plugin_dir",))
    config.log_file = (
        _resolve_path(base / config.log_file, field=("log_file",))
        if config.log_file
        else config.data_dir / "logagent.log"
    )
    return config


async def load_system_config(path: str | Path) -> SystemConfig:
    return await run_io(_load_system_config, Path(path))


def _load_plugin_config(path: Path) -> dict:
    try:
        value = read_json(path)
        if not isinstance(value, dict):
            raise TypeError("Plugin configuration must be a JSON object")
        validate_json_value(value)
        return value
    except FileNotFoundError:
        return {}
    except (ValueError, TypeError) as exc:
        raise LogAgentError(
            "PLUGIN_CONFIG_INVALID", "Plugin configuration must be a valid JSON object", {"file": path.name}
        ) from exc
    except OSError as exc:
        raise LogAgentError(
            "PLUGIN_CONFIG_UNAVAILABLE", "Cannot read plugin configuration", {"file": path.name}
        ) from exc


async def load_plugin_config(path: str | Path) -> dict:
    """Read one optional sibling JSON file; discovery owns per-plugin isolation."""
    return await run_io(_load_plugin_config, Path(path))


class ResourceStore:
    def __init__(self, root: str | Path, *, base_dir: str | Path | None = None):
        self.root = _resolve_path(Path(root), field=("root",))
        self.base_dir = _resolve_path(Path(base_dir), field=("base_dir",)) if base_dir is not None else self.root
        self._lock = asyncio.Lock()

    def _path(self, kind: str, resource_id: str) -> Path:
        if kind not in RESOURCE_MODELS:
            raise LogAgentError("VALIDATION_ERROR", "Unknown resource kind", {"kind": kind})
        validate_id(resource_id)
        path = self.root / kind / (resource_id + ".json")
        if not _resolve_path(path, field=(kind, resource_id)).is_relative_to(self.root):
            raise LogAgentError("VALIDATION_ERROR", "Resource path escapes its storage directory")
        return path

    def _read(self, kind: str, resource_id: str):
        path = self._path(kind, resource_id)
        try:
            value = read_json(path)
        except FileNotFoundError as exc:
            raise LogAgentError("NOT_FOUND", "Resource does not exist", {"kind": kind, "id": resource_id}) from exc
        except ValueError as exc:
            raise LogAgentError(
                "RESOURCE_CORRUPT",
                "Resource JSON is invalid",
                {"kind": kind, "id": resource_id, "reason": "invalid_json"},
            ) from exc
        try:
            model = RESOURCE_MODELS[kind].model_validate(value)
        except ValidationError as exc:
            raise LogAgentError(
                "RESOURCE_CORRUPT",
                "Resource schema is invalid",
                {"kind": kind, "id": resource_id, "reason": "invalid_schema", **validation_error(exc).details},
            ) from exc
        if model.id != resource_id:
            raise LogAgentError(
                "RESOURCE_CORRUPT",
                "Stored ID does not match its filename",
                {"kind": kind, "id": resource_id, "reason": "id_mismatch"},
            )
        return model

    def _list(self, kind: str):
        self._path(kind, "validation")
        directory = self.root / kind
        try:
            paths = sorted(path for path in directory.iterdir() if path.suffix == ".json")
        except FileNotFoundError:
            if directory.is_symlink():
                raise LogAgentError("CONFIG_UNAVAILABLE", "Resource directory is unavailable", {"kind": kind}) from None
            return []
        return [self._read(kind, path.stem) for path in paths]

    def _all(self):
        return {kind: {model.id: model for model in self._list(kind)} for kind in RESOURCE_MODELS}

    @staticmethod
    def _references(data):
        references = []
        for source in data["sources"].values():
            if source.template:
                references.append(("setters", source.template, "sources", source.id, "template"))
        for workflow in data["workflows"].values():
            for source_id in workflow.sources:
                references.append(("sources", source_id, "workflows", workflow.id, "sources"))
            for task in workflow.analyses:
                references.append(("ai", task.ai, "workflows", workflow.id, "analyses." + task.id + ".ai"))
            if workflow.fan_in and workflow.fan_in.ai:
                references.append(("ai", workflow.fan_in.ai, "workflows", workflow.id, "fan_in.ai"))
            for channel_id in workflow.channels:
                references.append(("channels", channel_id, "workflows", workflow.id, "channels"))
        return references

    @classmethod
    def _validate_references(cls, data):
        for kind, identifier, owner_kind, owner_id, field in cls._references(data):
            if identifier not in data[kind]:
                raise LogAgentError(
                    "VALIDATION_ERROR",
                    "Referenced resource does not exist",
                    {
                        "kind": kind,
                        "id": identifier,
                        "path": [owner_kind, owner_id, field],
                    },
                )
        for source in data["sources"].values():
            if source.template and data["setters"][source.template].collector != source.collector:
                raise LogAgentError(
                    "VALIDATION_ERROR",
                    "Setter template belongs to a different Collector",
                    {
                        "path": ["sources", source.id, "template"],
                    },
                )

    async def _operation(self, function, *args):
        async with self._lock:
            try:
                return await run_io(function, *args)
            except OSError as exc:
                raise LogAgentError("CONFIG_UNAVAILABLE", "Resource storage is unavailable") from exc

    async def get(self, kind: str, resource_id: str):
        return await self._operation(self._read, kind, resource_id)

    async def list(self, kind: str):
        return await self._operation(self._list, kind)

    async def save(self, kind: str, model, *, mode: str = "upsert"):
        if kind not in RESOURCE_MODELS or mode not in {"create", "replace", "upsert"}:
            raise LogAgentError("VALIDATION_ERROR", "Invalid resource kind or save mode")
        if isinstance(model, Model) and not isinstance(model, RESOURCE_MODELS[kind]):
            raise LogAgentError("VALIDATION_ERROR", "Resource kind and model do not match")
        try:
            value = model.model_dump(mode="python") if isinstance(model, Model) else deepcopy(model)
            validated = RESOURCE_MODELS[kind].model_validate(value)
        except ValidationError as exc:
            raise validation_error(exc, prefix=(kind,)) from exc
        return await self._operation(self._save, kind, validated, mode)

    def _save(self, kind, model, mode):
        path = self._path(kind, model.id)
        exists = path.exists()
        if mode == "create" and exists:
            raise LogAgentError("CONFLICT", "Resource already exists", {"kind": kind, "id": model.id})
        if mode == "replace" and not exists:
            raise LogAgentError("NOT_FOUND", "Resource does not exist", {"kind": kind, "id": model.id})
        data = self._all()
        data[kind][model.id] = model
        self._validate_references(data)
        atomic_write(path, json_bytes(model.model_dump(mode="json")))
        return model.model_copy(deep=True)

    async def delete(self, kind: str, resource_id: str):
        return await self._operation(self._delete, kind, resource_id)

    def _delete(self, kind, resource_id):
        self._read(kind, resource_id)
        users = [
            {"kind": owner_kind, "id": owner_id, "path": field}
            for target_kind, target_id, owner_kind, owner_id, field in self._references(self._all())
            if (kind, resource_id) == (target_kind, target_id)
        ]
        if users:
            raise LogAgentError("CONFLICT", "Resource is still referenced", {"references": users})
        self._path(kind, resource_id).unlink()

    def _snapshot(self, workflow_id=None, definition=None):
        data = self._all()
        workflow = definition if definition is not None else self._read("workflows", workflow_id)
        data["workflows"][workflow.id] = workflow
        self._validate_references(data)
        sources = {}
        for source_id in workflow.sources:
            source = data["sources"][source_id].model_copy(deep=True)
            inherited = deepcopy(data["setters"][source.template].setters) if source.template else {}
            inherited.update(source.setters)
            source.setters = inherited
            sources[source_id] = source
        ai_ids = list(dict.fromkeys(task.ai for task in workflow.analyses))
        if workflow.fan_in and workflow.fan_in.ai and workflow.fan_in.ai not in ai_ids:
            ai_ids.append(workflow.fan_in.ai)
        channels = {key: data["channels"][key].model_copy(deep=True) for key in workflow.channels}
        for channel in channels.values():
            if channel.channel == "file" and isinstance(channel.options.get("path"), str):
                channel.options["path"] = str(
                    _resolve_path(
                        self.base_dir / channel.options["path"],
                        field=("channels", channel.id, "options", "path"),
                    )
                )
        return WorkflowSnapshot(
            workflow=workflow.model_copy(deep=True),
            sources=sources,
            ai={key: data["ai"][key].model_copy(deep=True) for key in ai_ids},
            channels=channels,
        )

    async def snapshot(self, workflow_id: str) -> WorkflowSnapshot:
        validate_id(workflow_id)
        return await self._operation(self._snapshot, workflow_id)

    async def resolve(self, definition: WorkflowDefinition) -> WorkflowSnapshot:
        try:
            definition = WorkflowDefinition.model_validate(definition.model_dump(mode="python"))
        except ValidationError as exc:
            raise validation_error(exc) from exc
        return await self._operation(self._snapshot, None, definition)
