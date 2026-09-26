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

from logagent.config.calls import (
    normalize_call_options,
    resolve_channel_call,
    resolve_source_call,
    select_source_call,
)
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
    SourceOverride,
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
    except LogAgentError:
        # Preserve structured domain diagnostics so clients can identify the
        # rejected field or provider instead of seeing a generic wrapper.
        raise
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

    @staticmethod
    def _value(kind: str, resource: Any) -> StrictModel:
        try:
            return _MODELS[kind].model_validate(resource)
        except ValidationError as exc:
            raise validation_error(exc) from None

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

    def _snapshot(
        self,
        workflow: WorkflowDefinition,
        candidate: _Resources,
        *,
        for_execution: bool = True,
    ) -> WorkflowSnapshot:
        ai_ids = {task.ai for task in workflow.analyses}
        if workflow.fan_in is not None and workflow.fan_in.ai is not None:
            ai_ids.add(workflow.fan_in.ai)
        try:
            channels = {
                key: resolve_channel_call(candidate.channels[key], workflow.channel_overrides.get(key))
                for key in workflow.channels
            }
            enabled_sources = []
            for key in workflow.sources:
                source = select_source_call(
                    candidate.sources.get(key), workflow.source_overrides.get(key),
                )
                if not for_execution or source.enabled:
                    enabled_sources.append(key)
            if not enabled_sources:
                raise LogAgentError(
                    "workflow_no_enabled_sources",
                    "工作流没有可用的数据源，请先启用至少一个数据源",
                )
            snapshot_workflow = copy_model(workflow)
            snapshot_workflow.sources = enabled_sources
            snapshot_workflow.source_overrides = {
                key: copy_model(workflow.source_overrides[key])
                for key in enabled_sources
                if key in workflow.source_overrides
            }
            return WorkflowSnapshot(
                workflow=snapshot_workflow,
                sources={
                    key: resolve_source_call(
                        candidate.sources.get(key),
                        candidate.setters,
                        workflow.source_overrides.get(key),
                    )
                    for key in enabled_sources
                },
                ai={key: copy_model(candidate.ai[key]) for key in ai_ids},
                channels=channels,
                created_at=datetime.now(UTC),
            )
        except KeyError:
            raise LogAgentError("invalid_reference", "Workflow 引用的资源不存在") from None
        except ValidationError as exc:
            raise validation_error(exc) from None

    @staticmethod
    def _prepare_effective_source(
        source: SourceConfig,
        capability,
        *,
        data_dir: Path,
        apply_defaults: bool,
    ) -> bool:
        """Normalize and schema-check a source without consulting stored workflows."""
        normalized = normalize_options(
            source.options, capability.options_schema,
            data_dir=data_dir, apply_defaults=apply_defaults,
        )
        validate_instance(
            normalized, resource_options_schema(capability.options_schema), path=["options"],
        )
        validate_instance(source.setters, capability.setters_schema, path=["setters"])
        source.options = normalized
        if options_complete(normalized, capability.options_schema):
            validate_effective_source(source, capability)
            return True
        return False

    def _validate_workflow(self, workflow, candidate, *, changed):
        for ident, override in workflow.source_overrides.items():
            detached = override.source
            if detached is None:
                continue
            if detached.id != ident:
                raise LogAgentError("invalid_reference", "脱离的数据源快照与工作流绑定不匹配")
            capability = self._collectors.get(detached.collector) if self._collectors else None
            if capability is None:
                if changed:
                    raise LogAgentError("capability_missing", "脱离的数据源采集器能力不可用")
                continue
            self._prepare_effective_source(
                detached, capability, data_dir=self._data_dir, apply_defaults=False,
            )

        # Validate all saved bindings, including disabled ones; only execution filters them.
        snapshot = self._snapshot(workflow, candidate, for_execution=False)
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
                    override.options = normalize_call_options(
                        override.options, capability.options_schema,
                        data_dir=self._data_dir,
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
                        effective = resolve_source_call(value, candidate.setters)
                    if capability is None:
                        continue
                    if kind == "setters":
                        validate_instance(value.setters, capability.setters_schema, partial=True)
                    elif kind == "sources":
                        self._prepare_effective_source(
                            effective, capability, data_dir=self._data_dir,
                            apply_defaults=normalize and is_changed,
                        )
                        value.options = effective.options
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
        value = self._value(kind, resource)
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

    def save_many(self, resources: Mapping[ResourceKind, list[Any]]) -> None:
        """Validate and publish mutually dependent resource updates together."""
        with self._lock:
            data = self._view.model_dump(mode="python")
            changed: set[tuple[str, str]] = set()
            for resource_kind, values in resources.items():
                kind = self._kind(resource_kind)
                for resource in values:
                    value = self._value(kind, resource)
                    data[kind][value.id] = value.model_dump(mode="python")
                    changed.add((kind, value.id))
            if changed:
                self._commit(data, changed=changed)

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
                return resolve_source_call(candidate.sources[resource.id], candidate.setters)
            return self._snapshot(candidate.workflows[resource.id], candidate)

    def resolve_source(
        self, ident: str, override: SourceOverride | None = None,
    ) -> SourceConfig:
        """Return a validated, editable source with all referenced setters expanded."""
        with self._lock:
            if override is None:
                override = SourceOverride()
            elif isinstance(override, SourceOverride):
                override = copy_model(override)
            else:
                try:
                    override = SourceOverride.model_validate(override)
                except ValidationError as exc:
                    raise validation_error(exc) from None
            source = override.source
            if source is None:
                source = self._view.sources.get(ident)
                if source is None:
                    raise LogAgentError(
                        "not_found", "资源不存在", {"kind": "sources", "id": ident},
                    )
            if source.id != ident:
                raise LogAgentError("invalid_reference", "数据源快照与资源绑定不匹配")
            capability = self._collectors.get(source.collector) if self._collectors else None
            if capability is None:
                raise LogAgentError(
                    "capability_missing", "数据源引用的插件能力不可用",
                    {"name": source.collector},
                )
            override.options = normalize_call_options(
                override.options, capability.options_schema, data_dir=self._data_dir,
            )
            effective = resolve_source_call(source, self._view.setters, override)
            complete = self._prepare_effective_source(
                effective, capability, data_dir=self._data_dir, apply_defaults=True,
            )
            validator = self._validators.get("sources")
            if complete and validator is not None:
                _call_validator(validator, effective)
            return effective

    def snapshot(self, workflow_id: str) -> WorkflowSnapshot:
        with self._lock:
            workflow = self._view.workflows.get(workflow_id)
            if workflow is None:
                raise LogAgentError("not_found", "Workflow 不存在")
            return self._snapshot(workflow, self._view)

    def invocation_snapshot(self) -> dict[str, dict[str, StrictModel]]:
        """Capture all callable resources under the same publication lock."""
        with self._lock:
            return {
                "sources": {
                    key: resolve_source_call(value, self._view.setters)
                    for key, value in self._view.sources.items() if value.enabled
                },
                "channels": {
                    key: copy_model(value) for key, value in self._view.channels.items()
                    if value.enabled
                },
                "ai": {key: copy_model(value) for key, value in self._view.ai.items()},
            }

    def reload_resources(self) -> None:
        with self._lock:
            candidate = self._parse(read_json(Path(self.location)))
            changed = {
                (kind, ident) for kind in _MODELS
                for ident, value in getattr(candidate, kind).items()
                if getattr(self._view, kind).get(ident) != value
            }
            self._commit(candidate.model_dump(mode="python"), changed=changed)
