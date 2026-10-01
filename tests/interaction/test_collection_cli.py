"""The CLI validates local input and reports a single HTTP outcome."""

import json
import subprocess
import sys

import httpx
import pytest
from typer.testing import CliRunner

from logagent.interaction import cli


def test_cli_import_does_not_load_lifecycle_runtime() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import logagent.interaction.cli; "
            "print('logagent.lifecycle.service' in sys.modules)",
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
