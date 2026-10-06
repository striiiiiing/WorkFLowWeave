"""Named MCP envelope parsing keeps the external name as the service identity."""

import pytest
from pydantic import ValidationError

from workflowweave.models import MCPServerImportConfig

SAMPLE = {
    "servers": {
        "qqmusic-mcp": {
            "type": "stdio",
            "command": "qqmusic-mcp",
            "args": ["stdio"],
        }
    }
}


def test_named_import_preserves_service_name_and_transport():
    [server] = MCPServerImportConfig.model_validate(SAMPLE).to_resources()
    assert server.id == "qqmusic-mcp"
    assert server.transport == "stdio"
    assert server.command == "qqmusic-mcp"
    assert server.args == ["stdio"]


def test_named_import_accepts_mcp_servers_alias():
    [server] = MCPServerImportConfig.model_validate({"mcpServers": SAMPLE["servers"]}).to_resources()
    assert server.id == "qqmusic-mcp"


@pytest.mark.parametrize(
    "payload",
    [
        {"servers": []},
        {"servers": {"one": {"type": "unknown"}}},
    ],
)
def test_named_import_rejects_invalid_envelopes(payload):
    with pytest.raises(ValidationError):
        MCPServerImportConfig.model_validate(payload).to_resources()


def test_named_import_rejects_both_root_aliases():
    with pytest.raises(ValidationError):
        MCPServerImportConfig.model_validate({"servers": {}, "mcpServers": {}})
