"""The CLI validates local input and reports a single HTTP outcome."""

import json
import subprocess
import sys

import httpx
import pytest
from typer.testing import CliRunner

from workflowweave.interaction import cli


def test_cli_health_uses_default_server_port(monkeypatch):
    from workflowweave.models import SystemConfig

    monkeypatch.delenv("WORKFLOWWEAVE_API_URL", raising=False)
    requests = []
    client_class = httpx.Client

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr(cli.httpx, "Client", lambda **kwargs: client_class(
        **kwargs, transport=httpx.MockTransport(respond),
    ))
    result = CliRunner().invoke(cli.app, ["health"])

    assert result.exit_code == 0, result.output
    assert requests[0].url == f"http://127.0.0.1:{SystemConfig().port}/api/health"
    assert requests[0].url.port == 4333


def test_cli_import_does_not_load_lifecycle_runtime() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import workflowweave.interaction.cli; "
            "print('workflowweave.lifecycle.service' in sys.modules)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "False"


@pytest.mark.parametrize("body", ["[]", "null", "not-json", '{"secret":'])
def test_collect_rejects_malformed_argument_files_before_http(tmp_path, monkeypatch, body):
    def unexpected(**kwargs):
        raise AssertionError("Invalid local input must not send a request")

    monkeypatch.setattr(cli.httpx, "Client", unexpected)
    arguments = tmp_path / "bad.json"
    arguments.write_text(body, encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["collect", "logs", "-a", str(arguments)])
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "invalid_argument"
    assert "secret" not in result.output


@pytest.mark.parametrize("command", ["collect", "collect-schema"])
def test_collect_validates_source_id_before_building_url(monkeypatch, command):
    def unexpected(**kwargs):
        raise AssertionError("Invalid source ID must not reach HTTP")

    monkeypatch.setattr(cli.httpx, "Client", unexpected)
    result = CliRunner().invoke(cli.app, [command, "../workflows/trigger"])
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "invalid_argument"


@pytest.mark.parametrize("failure", ["transport", "validation", "unavailable"])
def test_collect_surfaces_http_failures_without_retries(monkeypatch, failure):
    requests = []
    client_class = httpx.Client

    def fail(request):
        requests.append(request)
        if failure == "transport":
            raise httpx.ReadError("secret response detail")
        status = 422 if failure == "validation" else 503
        return httpx.Response(status, json={"error": {"code": failure, "message": failure}})

    monkeypatch.setattr(cli.httpx, "Client", lambda **kwargs: client_class(
        **kwargs, transport=httpx.MockTransport(fail),
    ))
    result = CliRunner().invoke(cli.app, ["collect", "logs", "--api-url", "http://test"])
    assert result.exit_code == (2 if failure == "validation" else 1)
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {}
    assert "secret" not in result.output
    assert json.loads(result.stderr)["error"]["code"] == (
        "connection_failed" if failure == "transport" else failure
    )
