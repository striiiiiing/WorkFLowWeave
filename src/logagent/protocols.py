"""Dependency boundaries; concrete readers and registries are injected."""

from __future__ import annotations

from typing import Protocol

from logagent.models import (
    CapabilityDescription,
    ChannelConfig,
    CollectionContext,
    CollectorOutput,
    Credential,
    ErrorInfo,
    JSONObject,
    JSONSchema,
    Notification,
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

    async def create(
        self, config: ChannelConfig, credentials: CredentialResolver
    ) -> NotificationChannel: ...
