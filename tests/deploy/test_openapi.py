"""API documentation must remain valid for all supported source call forms."""

from fastapi.testclient import TestClient

from workflowweave.interaction.app import create_app


def test_openapi_is_available_with_nested_cli_call_modes():
    response = TestClient(create_app()).get("/openapi.json")
    assert response.status_code == 200, response.text
    schema = response.json()
    assert "/api/channels/{ident}/conversation" in schema["paths"]
    models = schema["components"]["schemas"]
    assert {"MCPCall", "CLIArgv", "CLIShell", "SourceConfig"} <= models.keys()
