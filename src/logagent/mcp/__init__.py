"""Shared MCP configuration, metadata and raw invocation boundary."""
from .runtime import MCPRuntime
from .transport import SDKConnector

__all__ = ["MCPRuntime", "SDKConnector"]
