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

from workflowweave.config.calls import (
    normalize_call_options,
    resolve_channel_call,
    resolve_source_call,
    select_source_call,
)
from workflowweave.config.migrations import RESOURCE_FORMAT_VERSION, migrate_resources
from workflowweave.config.normalize import normalize_options
from workflowweave.config.reader import read_json
from workflowweave.errors import WorkFLowWeaveError, validation_error
from workflowweave.models import (
    AIConfig,
    AtSchedule,
    ChannelConfig,
    MCPServerConfig,
    ResourceKind,
    SaveMode,
    SourceConfig,
    SourceOverride,
    StrictModel,
    WorkflowDefinition,
    WorkflowSnapshot,
    copy_model,
)
from workflowweave.protocols import ChannelRegistryView
from workflowweave.schema import (
    options_complete,
    resource_options_schema,
    validate_instance,
)

_MODELS = {
    "sources": SourceConfig, "mcp_servers": MCPServerConfig, "ai": AIConfig,
    "channels": ChannelConfig, "workflows": WorkflowDefinition,
}
Validator = Callable[[StrictModel], None]


class _Resources(StrictModel):
    format_version: int = Field(ge=RESOURCE_FORMAT_VERSION, le=RESOURCE_FORMAT_VERSION)
    sources: dict[str, SourceConfig]
    mcp_servers: dict[str, MCPServerConfig]
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
    except WorkFLowWeaveError:
        # Preserve structured domain diagnostics so clients can identify the
        # rejected field or provider instead of seeing a generic wrapper.
        raise
    except Exception as exc:
        raise WorkFLowWeaveError(
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
        channel_register: ChannelRegistryView | None = None,
        validators: Mapping[ResourceKind, Validator] | None = None,
        data_dir: str | Path | None = None,
        initial_resources: Mapping[ResourceKind, list[StrictModel]] | None = None,
    ) -> None:
        self.location = str(Path(location).absolute())
        self._data_dir = Path(data_dir or Path(self.location).parent).absolute()
        self._channels = channel_register
        self._validators = dict(validators or {})
        self._lock = threading.RLock()
        self._view = _Resources(format_version=RESOURCE_FORMAT_VERSION, **{kind: {} for kind in _MODELS})
        path = Path(self.location)
        if path.exists() or path.is_symlink():
            data, migrated = migrate_resources(read_json(path))
            candidate = self._parse(data)
            self._validate(candidate, changed=set(), normalize=False)
            if migrated:
                self._publish(candidate)
            else:
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
                raise WorkFLowWeaveError("invalid_config", "资源键必须与内部 ID 一致", {"kind": kind})
        return candidate

    @staticmethod
    def _kind(kind: str) -> str:
        if kind not in _MODELS:
            raise WorkFLowWeaveError("invalid_argument", "资源类型无效")
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
        channel_register: ChannelRegistryView,
        validators: Mapping[ResourceKind, Validator],
    ) -> None:
        """Install one published plugin generation without rewriting saved resources."""
        with self._lock:
            self._channels = channel_register
            self._validators = dict(validators)

    def _capability(self, value, changed):
        registry = self._channels
        name = value.channel
        capability = registry.get(name) if registry is not None else None
        if capability is None and changed:
            raise WorkFLowWeaveError("capability_missing", "新资源引用的插件能力不可用", {"name": name})
        return capability

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
                raise WorkFLowWeaveError(
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
            effective_sources = {
                key: resolve_source_call(
                    candidate.sources.get(key),
                    workflow.source_overrides.get(key),
                )
                for key in enabled_sources
            }
            server_ids = {
                source.call.server for source in effective_sources.values()
                if source.call.kind == "mcp"
            }
            snapshot = WorkflowSnapshot(
                workflow=snapshot_workflow,
                sources=effective_sources,
                ai={key: copy_model(candidate.ai[key]) for key in ai_ids},
                channels=channels,
                mcp_servers={server: copy_model(candidate.mcp_servers[server]) for server in server_ids},
                created_at=datetime.now(UTC),
            )
            return snapshot
        except KeyError:
            raise WorkFLowWeaveError("invalid_reference", "Workflow 引用的资源不存在") from None
        except ValidationError as exc:
            raise validation_error(exc) from None

    def _validate_workflow(self, workflow, candidate, *, changed):
        # Validate all saved bindings, including disabled ones; only execution filters them.
        snapshot = self._snapshot(workflow, candidate, for_execution=False)
        source_validator = self._validators.get("sources")
        if source_validator is not None:
            for source in snapshot.sources.values():
                _call_validator(source_validator, source)
        for ident, effective in snapshot.channels.items():
            capability = self._channels.get(effective.channel) if self._channels is not None else None
            if capability is None:
                if changed and ident in workflow.channel_overrides:
                    raise WorkFLowWeaveError("capability_missing", "调用覆盖引用的插件能力不可用")
                continue
            override = workflow.channel_overrides.get(ident)
            if override is not None:
                override.options = normalize_call_options(
                    override.options, capability.options_schema, data_dir=self._data_dir,
                )
                effective.options.update(deepcopy(override.options))
            validate_instance(effective.options, capability.options_schema, path=["options"])
            validator = self._validators.get("channels")
            if validator is not None:
                _call_validator(validator, effective)

    def _validate(self, candidate: _Resources, *, changed: set, normalize: bool) -> None:
        for kind in ("mcp_servers", "sources", "channels", "ai", "workflows"):
            for ident, value in getattr(candidate, kind).items():
                is_changed = (kind, ident) in changed
                effective = value
                if kind == "sources" and value.call.kind == "mcp":
                    if value.call.server not in candidate.mcp_servers:
                        raise WorkFLowWeaveError("invalid_reference", "来源引用的 MCP 服务不存在")
                if kind == "channels":
                    capability = self._capability(value, is_changed)
                    if capability is None:
                        continue
                    normalized = normalize_options(
                        value.options, capability.options_schema,
                        data_dir=self._data_dir, apply_defaults=normalize and is_changed,
                    )
                    validate_instance(normalized, resource_options_schema(capability.options_schema),
                                      path=["options"])
                    effective = copy_model(value)
                    effective.options = normalized
                    value.options = normalized
                    if not options_complete(effective.options, capability.options_schema):
                        continue
                if kind == "workflows":
                    self._validate_workflow(value, candidate, changed=is_changed)
                validator = self._validators.get(kind)
                if validator is not None:
                    _call_validator(validator, effective)

    def _publish(self, candidate: _Resources) -> None:
        path = Path(self.location)
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            serialized = candidate.model_dump(mode="json")
            payload = orjson.dumps(serialized, option=orjson.OPT_INDENT_2)
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".resources-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        except (OSError, ValueError):
            raise WorkFLowWeaveError("storage_failed", "资源文件原子保存失败") from None
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
            raise WorkFLowWeaveError("invalid_argument", "保存模式无效")
        value = self._value(kind, resource)
        with self._lock:
            data = self._view.model_dump(mode="python")
            exists = value.id in data[kind]
            if mode == "create" and exists:
                raise WorkFLowWeaveError("already_exists", "资源已存在")
            if mode == "replace" and not exists:
                raise WorkFLowWeaveError("not_found", "资源不存在")
            data[kind][value.id] = value.model_dump(mode="python")
            self._commit(data, changed={(kind, value.id)})
            return copy_model(getattr(self._view, kind)[value.id])

    def save_if_current(self, kind: ResourceKind, expected: StrictModel,
                        resource: StrictModel) -> StrictModel:
        """Publish an asynchronous result only against the snapshot it observed."""
        kind = self._kind(kind)
        if expected.id != resource.id:
            raise WorkFLowWeaveError("invalid_argument", "资源 ID 不一致")
        with self._lock:
            current = getattr(self._view, kind).get(expected.id)
            if current != expected:
                raise WorkFLowWeaveError("resource_changed", "资源已变更，请重新连接")
            return self.save(kind, resource, mode="replace")

    def consume_schedule(self, ident: str, expected: AtSchedule) -> bool:
        """Compare and consume under the publication lock before any run admission."""
        with self._lock:
            workflow = self._view.workflows.get(ident)
            if workflow is None or not workflow.enabled or workflow.schedule != expected:
                return False
            data = self._view.model_dump(mode="python")
            data["workflows"][ident]["schedule"] = None
            self._commit(data, changed=set(), normalize=False)
            return True

    def save_many(
        self, resources: Mapping[ResourceKind, list[Any]], *, mode: SaveMode = "upsert"
    ) -> None:
        """Validate and publish mutually dependent resource updates together."""
        if mode not in ("create", "replace", "upsert"):
            raise WorkFLowWeaveError("invalid_argument", "保存模式无效")
        with self._lock:
            data = self._view.model_dump(mode="python")
            changed: set[tuple[str, str]] = set()
            for resource_kind, values in resources.items():
                kind = self._kind(resource_kind)
                for resource in values:
                    value = self._value(kind, resource)
                    exists = value.id in data[kind]
                    if mode == "create" and exists:
                        raise WorkFLowWeaveError("already_exists", "资源已存在")
                    if mode == "replace" and not exists:
                        raise WorkFLowWeaveError("not_found", "资源不存在")
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
                raise WorkFLowWeaveError("not_found", "资源不存在")
            del data[kind][ident]
            try:
                self._commit(data, changed=set(), normalize=False)
            except WorkFLowWeaveError as exc:
                if exc.code == "invalid_reference":
                    raise WorkFLowWeaveError("reference_conflict", "资源仍被引用，不能删除") from None
                raise

    @overload
    def resolve(self, resource: SourceConfig) -> SourceConfig: ...

    @overload
    def resolve(self, resource: WorkflowDefinition) -> WorkflowSnapshot: ...

    def resolve(self, resource):
        with self._lock:
            if not isinstance(resource, (SourceConfig, WorkflowDefinition)):
                raise WorkFLowWeaveError("invalid_argument", "resolve 需要来源或 Workflow 定义")
            kind = "sources" if isinstance(resource, SourceConfig) else "workflows"
            data = self._view.model_dump(mode="python")
            data[kind][resource.id] = resource.model_dump(mode="python")
            candidate = self._parse(data)
            self._validate(candidate, changed={(kind, resource.id)}, normalize=True)
            if kind == "sources":
                return resolve_source_call(candidate.sources[resource.id])
            return self._snapshot(candidate.workflows[resource.id], candidate)

    def resolve_source(
        self, ident: str, override: SourceOverride | None = None,
    ) -> SourceConfig:
        """Return an independent effective source with invocation overrides."""
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
                    raise WorkFLowWeaveError(
                        "not_found", "资源不存在", {"kind": "sources", "id": ident},
                    )
            if source.id != ident:
                raise WorkFLowWeaveError("invalid_reference", "数据源快照与资源绑定不匹配")
            return resolve_source_call(source, override)

    def snapshot(self, workflow_id: str) -> WorkflowSnapshot:
        with self._lock:
            workflow = self._view.workflows.get(workflow_id)
            if workflow is None:
                raise WorkFLowWeaveError("not_found", "Workflow 不存在")
            return self._snapshot(workflow, self._view)

    def invocation_snapshot(self) -> dict[str, dict[str, StrictModel]]:
        """Capture all callable resources under the same publication lock."""
        with self._lock:
            return {
                "sources": {
                    key: resolve_source_call(value)
                    for key, value in self._view.sources.items() if value.enabled
                },
                "mcp_servers": {key: copy_model(value) for key, value in self._view.mcp_servers.items()},
                "channels": {
                    key: copy_model(value) for key, value in self._view.channels.items()
                    if value.enabled
                },
                "ai": {key: copy_model(value) for key, value in self._view.ai.items()},
            }

    def reload_resources(self) -> None:
        with self._lock:
            data, _ = migrate_resources(read_json(Path(self.location)))
            candidate = self._parse(data)
            changed = {
                (kind, ident) for kind in _MODELS
                for ident, value in getattr(candidate, kind).items()
                if getattr(self._view, kind).get(ident) != value
            }
            self._commit(candidate.model_dump(mode="python"), changed=changed)
