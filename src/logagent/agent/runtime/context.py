"""Per-turn dependencies injected through LangGraph's Runtime context."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from logagent.agent.config import AgentConfig
from logagent.agent.ports import (
    ArtifactStorePort,
    EventLogPort,
    GatewayPort,
    SandboxPort,
    ToolSchedulerPort,
    WorkspacePort,
)
from logagent.models import CollectionContext


@dataclass(slots=True)
class ToolScope:
    """Tasks started by tools during one graph run, awaited during cleanup."""

    tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    context_middleware: Any = None


@dataclass(frozen=True, slots=True)
class AgentContext:
    """The dependencies captured for one turn and shared with nodes and tools."""

    workspace: WorkspacePort
    sandbox: SandboxPort
    gateway: GatewayPort | None
    config: AgentConfig
    session_id: str
    turn_id: str
    branch_id: str
    event_log: EventLogPort
    scheduler: ToolSchedulerPort
    artifacts: ArtifactStorePort | None = None
    collection: CollectionContext | None = None
    tool_call_id: str | None = None
    read_enabled: bool = True
    on_boundary: Callable[..., Any] | None = None
    scope: ToolScope = field(default_factory=ToolScope)

    @property
    def tool_tasks(self) -> dict[str, asyncio.Task]:
        return self.scope.tasks

    @property
    def context_middleware(self):
        return self.scope.context_middleware
