"""Dependency boundaries; concrete readers and registries are injected."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol, overload

from logagent.models import (
    AtSchedule,
    CapabilityDescription,
    ChannelConfig,
    CollectionContext,
    CollectorOutput,
    Credential,
    ErrorInfo,
    JSONObject,
    JSONSchema,
    Notification,
    PhaseContent,
    ResourceKind,
    SaveMode,
    SessionRecord,
    SessionVersion,
    SourceConfig,
    StrictModel,
    UTCDateTime,
    WorkflowDefinition,
    WorkflowSnapshot,
    WorkflowStage,
)


class Collector(Protocol):
    name: str
    id_prefix: str | None
    description: str
    fields: list[str]
    count_unit: str
    options_schema: JSONSchema
    setters_schema: JSONSchema

    async def collect(
        self, options: JSONObject, setters: JSONObject, context: CollectionContext
    ) -> CollectorOutput: ...


class CollectorRegistryView(Protocol):
    def get(self, name: str) -> Collector | None: ...

    def describe(self) -> list[CapabilityDescription]: ...

    def diagnostics(self, name: str) -> list[ErrorInfo]: ...


class CredentialResolver(Protocol):
    async def resolve(self, credential: Credential) -> str: ...


class NotificationChannel(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def send(self, notification: Notification, *, options: JSONObject) -> None: ...


class ChannelType(Protocol):
    name: str
    id_prefix: str | None
    description: str
    capabilities: list[str]
    options_schema: JSONSchema

    async def create(
        self, config: ChannelConfig, credentials: CredentialResolver
    ) -> NotificationChannel: ...


class ChannelRegistryView(Protocol):
    def get(self, name: str) -> ChannelType | None: ...

    def describe(self) -> list[CapabilityDescription]: ...

    def diagnostics(self, name: str) -> list[ErrorInfo]: ...


class Tool(Protocol):
    name: str
    description: str
    input_schema: JSONSchema
    execution: Literal["read", "exclusive"]

    async def invoke(self, arguments: JSONObject, context: Any) -> JSONObject: ...


class ToolRegistryView(Protocol):
    def get(self, name: str) -> Tool | None: ...

    def describe(self) -> list[CapabilityDescription]: ...

    def diagnostics(self, name: str) -> list[ErrorInfo]: ...


class ResourceReader(Protocol):
    def get(self, kind: ResourceKind, ident: str) -> StrictModel | None: ...

    def list(self, kind: ResourceKind) -> list[StrictModel]: ...

    @overload
    def resolve(self, resource: SourceConfig) -> SourceConfig: ...

    @overload
    def resolve(self, resource: WorkflowDefinition) -> WorkflowSnapshot: ...

    def snapshot(self, workflow_id: str) -> WorkflowSnapshot: ...


class ResourceStore(ResourceReader, Protocol):
    def consume_schedule(self, ident: str, expected: AtSchedule) -> bool: ...

    def save(
        self, kind: ResourceKind, resource: StrictModel | JSONObject, *, mode: SaveMode = "upsert"
    ) -> StrictModel: ...

    def save_many(
        self, resources: Mapping[ResourceKind, list[Any]], *, mode: SaveMode = "upsert"
    ) -> None: ...

    def delete(self, kind: ResourceKind, ident: str) -> None: ...

    def reload_resources(self) -> None: ...


class SessionReader(Protocol):
    """Read business session data from SessionStore through SessionView.

    Lists contain the latest version for each session, newest first. Versions
    increase on new logical writes; replaying a write does not increase them.
    A selected version pins reads. Missing or expired content must not be
    replaced by content from the latest version.
    """

    async def list_sessions(
        self,
        workflow_id: str | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
        after: UTCDateTime | None = None,
        before: UTCDateTime | None = None,
        exclude_session_id: str | None = None,
    ) -> list[SessionRecord]: ...

    async def get_session(
        self, session_id: str, *, version: SessionVersion | None = None
    ) -> SessionRecord: ...

    async def get_phase_content(
        self, session_id: str, stage: WorkflowStage, *, version: SessionVersion
    ) -> PhaseContent: ...
