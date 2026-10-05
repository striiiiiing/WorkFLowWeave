"""Periodic MCP health checks owned by the application lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

from apscheduler.events import EVENT_SCHEDULER_SHUTDOWN
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from logagent.models import MCPServerConfig

from .runtime import MCPRuntime

logger = logging.getLogger(__name__)


class MCPHealthMonitor:
    """Keep one scheduled health check for each opted-in MCP server."""

    def __init__(self, runtime: MCPRuntime, resources) -> None:
        self._runtime = runtime
        self._resources = resources
        self.scheduler = AsyncIOScheduler(
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": None},
        )
        self._plans: dict[str, int] = {}

    def update(self, servers: Iterable[MCPServerConfig]) -> None:
        plans = {
            server.id: server.health_check_interval_minutes
            for server in servers
            if server.enabled and server.health_check_enabled
        }
        for ident in self._plans.keys() - plans.keys():
            if self.scheduler.get_job(ident) is not None:
                self.scheduler.remove_job(ident)
        for ident, minutes in plans.items():
            if self._plans.get(ident) == minutes and self.scheduler.get_job(ident) is not None:
                continue
            if self.scheduler.get_job(ident) is not None:
                self.scheduler.remove_job(ident)
            self.scheduler.add_job(
                self._execute,
                IntervalTrigger(minutes=minutes),
                id=ident,
                replace_existing=True,
                args=(ident,),
            )
        self._plans = plans

    async def _execute(self, ident: str) -> None:
        server = self._resources.get("mcp_servers", ident)
        if server is None or not server.enabled or not server.health_check_enabled:
            return
        try:
            await self._runtime.probe({ident: server}, ident)
        except Exception:
            logger.exception("mcp_health_check_failed", extra={"server": ident})

    def start(self) -> None:
        self.scheduler.start()

    async def stop(self) -> None:
        if not self.scheduler.running:
            return
        stopped = asyncio.get_running_loop().create_future()

        def on_shutdown(event):
            if not stopped.done():
                stopped.set_result(None)

        self.scheduler.add_listener(on_shutdown, EVENT_SCHEDULER_SHUTDOWN)
        try:
            self.scheduler.shutdown(wait=True)
            await stopped
        finally:
            self.scheduler.remove_listener(on_shutdown)
