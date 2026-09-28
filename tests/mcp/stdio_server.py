"""Local real MCP server used by contract and browser smoke tests."""
from typing import Any

from mcp.server.fastmcp import FastMCP

server = FastMCP("LogAgent contract fixture")

@server.tool()
def echo(value: str, count: int = 1) -> dict[str, Any]:
    """Return the supplied value as JSON."""
    return {"value": value, "count": count}

@server.tool()
def fail() -> str:
    """Return an explicit tool error."""
    raise ValueError("fixture failure")

if __name__ == "__main__":
    server.run(transport="stdio")
