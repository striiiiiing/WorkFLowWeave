"""Dependency boundaries; concrete readers and registries are injected."""

from __future__ import annotations

from typing import Protocol

from logagent.models import (
    ArtifactAvailability,
    ArtifactContent,
    ArtifactName,
    CapabilityDescription,
    ChannelConfig,
    CollectionContext,
    CollectorOutput,
    Credential,
    ErrorInfo,
    JSONObject,
    JSONSchema,
    Notification,
    SessionRecord,
)


class Collector(Protocol):
    name: str
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


class ArchiveReader(Protocol):
    async def get(self, session_id: str) -> SessionRecord: ...

    async def list(
        self, workflow_id: str | None = None, limit: int | None = 100
    ) -> list[SessionRecord]: ...

    async def load_artifact(self, session_id: str, name: ArtifactName) -> ArtifactContent: ...

    async def availability(self, session_id: str) -> ArtifactAvailability: ...


class CredentialResolver(Protocol):
    async def resolve(self, credential: Credential) -> str: ...


class NotificationChannel(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def send(self, notification: Notification) -> None: ...


class ChannelType(Protocol):
    name: str
    description: str
    capabilities: list[str]
    options_schema: JSONSchema

    def create(
        self, config: ChannelConfig, credentials: CredentialResolver
    ) -> NotificationChannel: ...
