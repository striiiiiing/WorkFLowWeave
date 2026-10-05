from contextlib import asynccontextmanager

import pytest

from logagent.mcp import MCPHealthMonitor, MCPRuntime
from logagent.models import MCPServerConfig


def server(**overrides):
    return MCPServerConfig(
        id="server",
        transport="stdio",
        command="mcp-server",
        **overrides,
    )


class Resources:
    def __init__(self, value):
        self.value = value

    def get(self, kind, ident):
        return self.value if kind == "mcp_servers" and ident == self.value.id else None


@pytest.mark.asyncio
async def test_monitor_uses_configured_minute_interval_and_reconfigures():
    monitor = MCPHealthMonitor(MCPRuntime(Connector()), Resources(server()))
    monitor.update([server(health_check_enabled=True, health_check_interval_minutes=30)])
    job = monitor.scheduler.get_job("server")
    assert job is not None
    assert job.trigger.interval.total_seconds() == 30 * 60

    monitor.update([server(health_check_enabled=True, health_check_interval_minutes=10_000_001)])
    job = monitor.scheduler.get_job("server")
    assert job is not None
    assert job.trigger.interval.total_seconds() == 10_000_001 * 60

    monitor.update([server(health_check_enabled=False)])
    assert monitor.scheduler.get_job("server") is None


class Connector:
    @asynccontextmanager
    async def connect(self, config, context):
        yield self
