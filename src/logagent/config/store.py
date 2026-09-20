"""One published resource view, backed by an atomically replaced JSON document."""

from __future__ import annotations

import inspect
import os
import tempfile
import threading
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, overload

import orjson
from pydantic import Field, ValidationError

from logagent.config.normalize import normalize_options, validate_effective_source
from logagent.config.reader import read_json
from logagent.errors import LogAgentError, validation_error
from logagent.models import (
    AIConfig,
    ChannelConfig,
    ResourceKind,
    SaveMode,
    SetterTemplate,
    SourceConfig,
    StrictModel,
    WorkflowDefinition,
    WorkflowSnapshot,
    copy_model,
)
from logagent.protocols import ChannelRegistryView, CollectorRegistryView
from logagent.schema import (
    options_complete,
    resource_options_schema,
    validate_instance,
    validate_workflow_options,
)

_MODELS = {
    "sources": SourceConfig, "setters": SetterTemplate, "ai": AIConfig,
    "channels": ChannelConfig, "workflows": WorkflowDefinition,
}
Validator = Callable[[StrictModel], None]


class _Resources(StrictModel):
    format_version: int = Field(ge=1, le=1)
    sources: dict[str, SourceConfig]
    setters: dict[str, SetterTemplate]
    ai: dict[str, AIConfig]
    channels: dict[str, ChannelConfig]
    workflows: dict[str, WorkflowDefinition]


def _call_validator(validator: Validator, value: StrictModel) -> None:
    # Validators are pure synchronous hooks; never turn arbitrary plugin text
    # into public configuration errors or let an async hook go unawaited.
    try:
        result = validator(copy_model(value))
        if inspect.iscoroutine(result):
            result.close()
        if result is not None:
            raise TypeError("Validator must return None")
    except Exception as exc:
        raise LogAgentError(
            "invalid_config", "资源未通过业务校验", {"exception_type": type(exc).__name__}
        ) from None


class ResourceStore:
    """CRUD, reload and snapshots share one lock and one candidate validation path.

    Existing files may reference unavailable plugins. New or changed resources
    require their declared capabilities; snapshots do not recheck availability.
    """

    def __init__(
        self,
        location: str | Path = "data/resources.json",
        *,
        collector_register: CollectorRegistryView | None = None,
        channel_register: ChannelRegistryView | None = None,
        validators: Mapping[ResourceKind, Validator] | None = None,
        data_dir: str | Path | None = None,
        initial_resources: Mapping[ResourceKind, list[StrictModel]] | None = None,
    ) -> None:
        self.location = str(Path(location).absolute())
        self._data_dir = Path(data_dir or Path(self.location).parent).absolute()
        self._collectors, self._channels = collector_register, channel_register
        self._validators = dict(validators or {})
        self._lock = threading.RLock()
        self._view = _Resources(format_version=1, **{kind: {} for kind in _MODELS})
        path = Path(self.location)
        if path.exists() or path.is_symlink():
            candidate = self._parse(read_json(path))
            self._validate(candidate, changed=set(), normalize=False)
            self._view = candidate
        else:
            for kind, values in (initial_resources or {}).items():
                target = getattr(self._view, self._kind(kind))
                for value in values:
                    target[value.id] = _MODELS[kind].model_validate(value)
            self._validate(
                self._view,
                changed={(kind, ident) for kind in _MODELS for ident in getattr(self._view, kind)},
                normalize=True,
            )
            self._publish(self._view)

    @staticmethod
    def _parse(data: Any) -> _Resources:
        try:
            candidate = _Resources.model_validate(data)
        except ValidationError as exc:
            raise validation_error(exc) from None
        for kind in _MODELS:
            if any(key != value.id for key, value in getattr(candidate, kind).items()):
                raise LogAgentError("invalid_config", "资源键必须与内部 ID 一致", {"kind": kind})
        return candidate

    @staticmethod
    def _kind(kind: str) -> str:
        if kind not in _MODELS:
            raise LogAgentError("invalid_argument", "资源类型无效")
        return kind

    def update_dependencies(
        self,
        *,
        collector_register: CollectorRegistryView,
        channel_register: ChannelRegistryView,
        validators: Mapping[ResourceKind, Validator],
    ) -> None:
        """Install one published plugin generation without rewriting saved resources."""
        with self._lock:
            self._collectors, self._channels = collector_register, channel_register
            self._validators = dict(validators)

    def _capability(self, kind, value, changed):
        registry = self._collectors if kind in ("sources", "setters") else self._channels
        name = value.collector if kind in ("sources", "setters") else value.channel
        capability = registry.get(name) if registry is not None else None
        if capability is None and changed:
            raise LogAgentError("capability_missing", "新资源引用的插件能力不可用", {"name": name})
        return registry, capability

    @staticmethod
    def _source(source: SourceConfig, candidate: _Resources, override=None) -> SourceConfig:
        source = copy_model(source)
        templates = [(source.template, source.setters)]
        if override is not None:
            templates.append((override.template, override.setters))
            source.options = {**source.options, **deepcopy(override.options)}
        setters = {}
        for template_id, explicit in templates:
            if template_id is not None:
                template = candidate.setters.get(template_id)
                if template is None:
                    raise LogAgentError("invalid_reference", "来源引用的 Setter 模板不存在")
                if template.collector != source.collector:
                    raise LogAgentError("invalid_reference", "Setter 模板与来源的 Collector 不同")
                setters.update(deepcopy(template.setters))
            setters.update(deepcopy(explicit))
        source.setters = setters
        source.template = None
        return source

    def _snapshot(self, workflow: WorkflowDefinition, candidate: _Resources) -> WorkflowSnapshot:
        ai_ids = {task.ai for task in workflow.analyses}
        if workflow.fan_in is not None and workflow.fan_in.ai is not None:
            ai_ids.add(workflow.fan_in.ai)
        try:
            channels = {key: copy_model(candidate.channels[key]) for key in workflow.channels}
            for key, override in workflow.channel_overrides.items():
                channels[key].options = {**channels[key].options, **deepcopy(override.options)}
            enabled_sources = [key for key in workflow.sources if candidate.sources[key].enabled]
            snapshot_workflow = copy_model(workflow)
            snapshot_workflow.sources = enabled_sources
            return WorkflowSnapshot(
                workflow=snapshot_workflow,
                sources={key: self._source(candidate.sources[key], candidate,
                                          workflow.source_overrides.get(key))
                         for key in enabled_sources},
                ai={key: copy_model(candidate.ai[key]) for key in ai_ids},
                channels=channels,
                created_at=datetime.now(UTC),
            )
        except KeyError:
            raise LogAgentError("invalid_reference", "Workflow 引用的资源不存在") from None
        except ValidationError as exc:
            raise validation_error(exc) from None

    def _validate_workflow(self, workflow, candidate, *, changed):
        snapshot = self._snapshot(workflow, candidate)
        for kind, resources, overrides, registry in (
            ("sources", snapshot.sources, workflow.source_overrides, self._collectors),
            ("channels", snapshot.channels, workflow.channel_overrides, self._channels),
        ):
            for ident, effective in resources.items():
                name = effective.collector if kind == "sources" else effective.channel
                capability = registry.get(name) if registry is not None else None
                if capability is None:
                    if changed and ident in overrides:
                        raise LogAgentError("capability_missing", "调用覆盖引用的插件能力不可用")
                    continue
                override = overrides.get(ident)
                if override is not None:
                    validate_workflow_options(override.options, capability.options_schema)
                    override.options = normalize_options(
                        override.options, capability.options_schema,
                        data_dir=self._data_dir, apply_defaults=False,
                    )
                    effective.options.update(deepcopy(override.options))
                if kind == "sources":
                    validate_effective_source(effective, capability)
                else:
                    validate_instance(effective.options, capability.options_schema, path=["options"])
                validator = self._validators.get(kind)
                if validator is not None:
                    _call_validator(validator, effective)

    def _validate(self, candidate: _Resources, *, changed: set, normalize: bool) -> None:
        for kind in ("setters", "sources", "channels", "ai", "workflows"):
            for ident, value in getattr(candidate, kind).items():
                is_changed = (kind, ident) in changed
                effective = value
                if kind in ("sources", "setters", "channels"):
                    registry, capability = self._capability(kind, value, is_changed)
                    if kind == "sources":
                        effective = self._source(value, candidate)
                    if capability is None:
                        continue
                    if kind == "setters":
                        validate_instance(value.setters, capability.setters_schema, partial=True)
                    elif kind == "sources":
                        normalized = normalize_options(
                            value.options, capability.options_schema,
                            data_dir=self._data_dir, apply_defaults=normalize and is_changed,
                        )
                        effective.options = normalized
                        validate_instance(normalized, resource_options_schema(capability.options_schema),
                                          path=["options"])
                        validate_instance(effective.setters, capability.setters_schema,
                                          path=["setters"])
                        if options_complete(normalized, capability.options_schema):
                            validate_effective_source(effective, capability)
                        value.options = normalized
                    else:
                        normalized = normalize_options(
                            value.options, capability.options_schema,
                            data_dir=self._data_dir, apply_defaults=normalize and is_changed,
                        )
                        validate_instance(normalized, resource_options_schema(capability.options_schema),
                                          path=["options"])
                        effective = copy_model(value)
                        effective.options = normalized
                        value.options = normalized
                if kind == "workflows":
                    self._validate_workflow(value, candidate, changed=is_changed)
                validator = self._validators.get(kind)
                # Runtime validators require a complete call. Deferred call
                # fields are validated after workflow binding above.
                if validator is not None:
                    if kind in ("sources", "channels") and not options_complete(
                        effective.options, capability.options_schema
                    ):
                        continue
                    _call_validator(validator, effective)

    def _publish(self, candidate: _Resources) -> None:
        path = Path(self.location)
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = orjson.dumps(candidate.model_dump(mode="json"), option=orjson.OPT_INDENT_2)
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".resources-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        except (OSError, ValueError):
            raise LogAgentError("storage_failed", "资源文件原子保存失败") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._view = candidate

    def _commit(self, data, *, changed: set, normalize=True) -> None:
        candidate = self._parse(data)
        self._validate(candidate, changed=changed, normalize=normalize)
        self._publish(candidate)

    def save(self, kind: ResourceKind, resource: Any, *, mode: SaveMode = "upsert") -> StrictModel:
        kind = self._kind(kind)
        if mode not in ("create", "replace", "upsert"):
            raise LogAgentError("invalid_argument", "保存模式无效")
        try:
            value = _MODELS[kind].model_validate(resource)
        except ValidationError as exc:
            raise validation_error(exc) from None
        with self._lock:
            data = self._view.model_dump(mode="python")
            exists = value.id in data[kind]
            if mode == "create" and exists:
                raise LogAgentError("already_exists", "资源已存在")
            if mode == "replace" and not exists:
                raise LogAgentError("not_found", "资源不存在")
            data[kind][value.id] = value.model_dump(mode="python")
            self._commit(data, changed={(kind, value.id)})
            return copy_model(getattr(self._view, kind)[value.id])

    def get(self, kind: ResourceKind, ident: str) -> StrictModel | None:
        with self._lock:
            value = getattr(self._view, self._kind(kind)).get(ident)
            return copy_model(value) if value is not None else None

    def list(self, kind: ResourceKind) -> list[StrictModel]:
        with self._lock:
            values = getattr(self._view, self._kind(kind))
            return [copy_model(values[key]) for key in sorted(values)]

    def delete(self, kind: ResourceKind, ident: str) -> None:
        kind = self._kind(kind)
        with self._lock:
            data = self._view.model_dump(mode="python")
            if ident not in data[kind]:
                raise LogAgentError("not_found", "资源不存在")
            del data[kind][ident]
            try:
                self._commit(data, changed=set(), normalize=False)
            except LogAgentError as exc:
                if exc.code == "invalid_reference":
                    raise LogAgentError("reference_conflict", "资源仍被引用，不能删除") from None
                raise

    @overload
    def resolve(self, resource: SourceConfig) -> SourceConfig: ...

    @overload
    def resolve(self, resource: WorkflowDefinition) -> WorkflowSnapshot: ...

    def resolve(self, resource):
        with self._lock:
            if not isinstance(resource, (SourceConfig, WorkflowDefinition)):
                raise LogAgentError("invalid_argument", "resolve 需要来源或 Workflow 定义")
            kind = "sources" if isinstance(resource, SourceConfig) else "workflows"
            data = self._view.model_dump(mode="python")
            data[kind][resource.id] = resource.model_dump(mode="python")
            candidate = self._parse(data)
            self._validate(candidate, changed={(kind, resource.id)}, normalize=True)
            if kind == "sources":
                return self._source(candidate.sources[resource.id], candidate)
            return self._snapshot(candidate.workflows[resource.id], candidate)

    def snapshot(self, workflow_id: str) -> WorkflowSnapshot:
        with self._lock:
            workflow = self._view.workflows.get(workflow_id)
            if workflow is None:
                raise LogAgentError("not_found", "Workflow 不存在")
            return self._snapshot(workflow, self._view)

    def reload_resources(self) -> None:
        with self._lock:
            candidate = self._parse(read_json(Path(self.location)))
            changed = {
                (kind, ident) for kind in _MODELS
                for ident, value in getattr(candidate, kind).items()
                if getattr(self._view, kind).get(ident) != value
            }
            self._commit(candidate.model_dump(mode="python"), changed=changed)
