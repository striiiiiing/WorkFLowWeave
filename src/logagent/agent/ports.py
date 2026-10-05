"""Consumer-sized capabilities passed into the Agent runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from .contracts import SessionView


class SessionRepository(Protocol):
    def get(self, session_id: str) -> SessionView: ...

    def log(self, session_id: str) -> Any: ...

    async def persist(self, session: SessionView) -> None: ...

    def document(self, session: SessionView) -> dict[str, Any]: ...


class ModelLease(Protocol):
    def lease(self, session: SessionView, *, output_tokens: int,
              ai_config: Any = None, model: str | None = None) -> AsyncIterator[Any]: ...


class ResourcePublication(Protocol):
    def invocation_snapshot(self) -> dict[str, Any]: ...


class CheckpointRuntime(Protocol):
    async def aget_tuple(self, config: dict) -> Any: ...

class WorkspacePort(Protocol):
    async def read(self, **arguments: Any) -> dict[str, Any]: ...

    async def write(self, **arguments: Any) -> dict[str, Any]: ...

    async def grep(self, **arguments: Any) -> dict[str, Any]: ...

    async def save_runtime(self, path: str, content: bytes) -> Any: ...


class ToolReservationPort(Protocol):
    status: str
    result: dict[str, Any] | None


class EventLogPort(Protocol):
    events: list[dict[str, Any]]

    async def append(self, event_type: str, **fields: Any) -> dict[str, Any]: ...

    async def reserve_tool(self, key: str, arguments: dict[str, Any],
                           **metadata: Any) -> ToolReservationPort: ...

    async def wait_for_tool(self, key: str, arguments: dict[str, Any]) -> ToolReservationPort: ...

    async def complete_tool(self, key: str, arguments: dict[str, Any],
                            result: dict[str, Any]) -> Any: ...

    async def mark_unknown(self, key: str, arguments: dict[str, Any], *, reason: str) -> Any: ...


class ToolSchedulerPort(Protocol):
    def acquire(self, execution: str) -> AbstractAsyncContextManager[None]: ...


class ArtifactStorePort(Protocol):
    async def save(self, result: dict[str, Any], **options: Any) -> dict[str, Any]: ...


class GatewayPort(Protocol):
    def execution(self, arguments: dict[str, Any]) -> str: ...

    async def catalog(self, workspace: WorkspacePort, *, revision: str) -> str: ...

    async def invoke(self, arguments: dict[str, Any], context: ToolContextPort) -> dict[str, Any]: ...


class SandboxPort(Protocol):
    async def run(self, **arguments: Any) -> dict[str, Any]: ...


class ToolContextPort(Protocol):
    workspace: WorkspacePort
    sandbox: Any
    gateway: GatewayPort | None
    config: Any
    session_id: str
    turn_id: str
    branch_id: str
    tool_call_id: str | None


class ToolDeclarationPort(Protocol):
    name: str
    description: str
    input_schema: Any
    execution: str

    async def invoke(self, arguments: dict[str, Any], context: ToolContextPort) -> Any: ...
