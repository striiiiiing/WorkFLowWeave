"""Request-scoped access to the lifecycle-owned services."""

from __future__ import annotations

from typing import Literal, Protocol

from fastapi import Request

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.lifecycle import ApplicationServices
from workflowweave.models import DiscoveryReport, HealthReport


class Lifecycle(Protocol):
    async def start(self) -> ApplicationServices: ...

    async def shutdown(self) -> None: ...

    async def health(self) -> HealthReport: ...

    async def reload(self, scope: Literal["resources", "plugins"]) -> DiscoveryReport | None: ...

    async def update_plugin_setting(self, plugin_id: str, enabled: bool) -> DiscoveryReport: ...


def get_services(request: Request) -> ApplicationServices:
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise WorkFLowWeaveError("not_ready", "应用尚未完成启动")
    return services


def get_lifecycle(request: Request) -> Lifecycle:
    lifecycle = getattr(request.app.state, "lifecycle", None)
    if lifecycle is None:
        raise WorkFLowWeaveError("not_ready", "应用生命周期尚未装配")
    return lifecycle
