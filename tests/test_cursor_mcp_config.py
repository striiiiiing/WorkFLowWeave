"""Cursor MCP envelope parsing keeps the external name as the service identity."""

import pytest
from pydantic import ValidationError

from logagent.models import CursorMCPConfig

SAMPLE = {
    "servers": {
        "qqmusic-mcp": {
            "type": "stdio",
            "command": "qqmusic-mcp",
            "args": ["stdio"],
        }
    }
}


def test_cursor_stdio_name_and_hyphen_are_preserved():
    [server] = CursorMCPConfig.model_validate(SAMPLE).to_resources()

    assert server.id == "qqmusic-mcp"
    assert server.transport == "stdio"
    assert server.command == "qqmusic-mcp"
    assert server.args == ["stdio"]


def test_cursor_mcp_servers_alias_maps_to_same_envelope():
    [server] = CursorMCPConfig.model_validate({"mcpServers": SAMPLE["servers"]}).to_resources()

    assert server.id == "qqmusic-mcp"


@pytest.mark.parametrize(
    "payload",
    [
        {"servers": {"bad.name": {"command": "x"}}},
        {"servers": {"qqmusic-mcp": {"type": "unknown", "command": "x"}}},
        {"servers": {"qqmusic-mcp": {"type": "stdio"}}},
    ],
)
def test_cursor_invalid_server_is_rejected(payload):
    with pytest.raises(ValidationError):
        CursorMCPConfig.model_validate(payload).to_resources()


def test_cursor_envelope_cannot_use_both_root_aliases():
    with pytest.raises(ValidationError):
        CursorMCPConfig.model_validate({"servers": {}, "mcpServers": {}})
