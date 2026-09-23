"""Exercise the shared Collector boundary through Agent, HTTP and the thin CLI."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from logagent.agent.config import AgentConfig
from logagent.agent.gateway import InvocationSnapshot, PluginGateway
from logagent.agent.scheduling import ToolScheduler
from logagent.collection import CollectorManager, MockCollector
from logagent.collection.invocation import CollectorInvocation
from logagent.config import ResourceStore
from logagent.config.views import CollectorRegister, collector_registration
from logagent.interaction import cli
from logagent.interaction.app import create_app
from logagent.models import (
    CollectionContext,
    CollectorOutput,
    ErrorInfo,
    SetterTemplate,
    SourceConfig,
    SystemConfig,
)
from logagent.schema import validate_instance


class RecordingCollector(MockCollector):
    options_schema = deepcopy(MockCollector.options_schema)
    options_schema["properties"]["account"] = {
        "type": "string", "description": "Saved instance account",
    }

    def __init__(self):
        self.calls = []
        self.started = asyncio.Event()
        self.cleaned = asyncio.Event()
        self.missing = False

    async def collect(self, options, setters, context):
        self.calls.append((deepcopy(options), deepcopy(setters), context))
        self.started.set()
        try:
            if self.missing:
                return CollectorOutput(
                    status="missing", error=ErrorInfo(code="missing", message="Missing input"),
                )
            return await super().collect(options, setters, context)
        finally:
            self.cleaned.set()


@pytest.fixture
def boundary(tmp_path):
    collector = RecordingCollector()
    register = CollectorRegister({"mock": collector_registration(collector, "test")})
    resources = ResourceStore(
        tmp_path / "resources.json", collector_register=register,
        initial_resources={
            "setters": [SetterTemplate(id="projection", collector="mock",
                                       setters={"fields": ["message"]})],
            "sources": [SourceConfig(
                id="logs", collector="mock", template="projection",
                options={"account": "private", "records": [{"message": "saved", "level": "INFO"}]},
                setters={"filter": {"level": "INFO"}}, timeout=0.1,
            )],
        },
    )
    services = SimpleNamespace(
        resources=resources, plugins=SimpleNamespace(collectorRegister=register),
        collectors=CollectorManager(register), system_config=SystemConfig(data_dir=str(tmp_path)),
        log_path=str(tmp_path / "app.jsonl"), credentials=object(), session_view=object(),
        agent=None,
    )
    application = create_app()
    application.state.services = services
    gateway = PluginGateway(
        InvocationSnapshot(1, resources.invocation_snapshot(), register, None, None),
        collectors=services.collectors, channels=None, data_dir=tmp_path,
    )
    invocation = CollectorInvocation(
        resources.invocation_snapshot()["sources"], register.describe(),
        executor=services.collectors, data_dir=tmp_path,
    )
    return SimpleNamespace(app=application, services=services, collector=collector,
                           gateway=gateway, invocation=invocation)


def client_for(boundary):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=boundary.app), base_url="http://test",
    )


@pytest.mark.parametrize("arguments, expected", [({}, "success"),
                                                   ({"setters": {"fields": []}}, "filtered_empty")])
async def test_agent_service_and_http_share_templates_overrides_and_saved_values(
    boundary, arguments, expected,
):
    saved = boundary.services.resources.get("sources", "logs")
    context = CollectionContext("agent", "session")
    direct = await boundary.invocation.invoke("logs", arguments, context)
    agent = await boundary.gateway.invoke(
        {"action": "call", "target": "sources:logs", "arguments": arguments},
        SimpleNamespace(config=AgentConfig(), collection=context),
    )
    async with client_for(boundary) as client:
        response = await client.post("/api/sources/logs/collect", json=arguments)
        schema = await client.get("/api/sources/logs/call-schema")
    assert response.status_code == schema.status_code == 200
    assert direct.model_dump(mode="json") == agent == response.json()
    assert response.json()["status"] == expected
    assert len(boundary.collector.calls) == 3
    assert all(call[:2] == boundary.collector.calls[0][:2] for call in boundary.collector.calls)
    assert boundary.collector.calls[0][0]["records"] == [{"message": "saved", "level": "INFO"}]
    assert boundary.collector.calls[0][1] == {
        "fields": arguments.get("setters", {}).get("fields", ["message"]), "filter": {"level": "INFO"},
    }
    http_context = boundary.collector.calls[-1][2]
    assert http_context.workflow_id == "collection" and len(http_context.session_id) == 32
    assert http_context.credentials is boundary.services.credentials
    assert http_context.session_reader is boundary.services.session_view
    assert http_context.log_path == boundary.services.log_path
    assert boundary.services.resources.get("sources", "logs") == saved
    assert schema.json() == boundary.gateway.schema("sources:logs")
    assert "private" not in json.dumps(schema.json())
    assert "account" not in schema.json()["properties"]["options"]["properties"]
    validate_instance(arguments, schema.json())


async def test_http_captures_new_resources_while_agent_keeps_its_round_snapshot(boundary):
    updated = boundary.services.resources.get("sources", "logs")
    updated.options["records"] = [{"message": "new", "level": "INFO"}]
    boundary.services.resources.save("sources", updated)
    async with client_for(boundary) as client:
        response = await client.post("/api/sources/logs/collect", json={})
    assert response.json()["items"] == [{"message": "new"}]
    old = await boundary.gateway.invoke(
        {"action": "call", "target": "sources:logs"},
        SimpleNamespace(collection=CollectionContext("agent", "session")),
    )
    assert old["items"] == [{"message": "saved"}]


@pytest.mark.parametrize("arguments, http_status", [
    ({"options": {"account": "secret-override"}}, 422), ({"options": {"mode": 1}}, 200),
    ({"setters": []}, 422), ({"setters": {"fields": [1]}}, 200),
    ({"context": {"credentials": "secret-override"}}, 422), ({"timeout": 500}, 422),
    ([], 422), (None, 422),
])
async def test_http_rejects_invalid_call_arguments_without_collecting(
    boundary, arguments, http_status,
):
    async with client_for(boundary) as client:
        response = await client.post("/api/sources/logs/collect", json=arguments)
    # Collector-specific value validation is a failed collection fact, as in Agent calls.
    assert response.status_code == http_status
    if http_status == 200:
        assert response.json()["status"] == "failed"
    assert "secret-override" not in response.text
    assert boundary.collector.calls == []


@pytest.mark.parametrize("state", ["absent", "disabled", "plugin_unavailable"])
async def test_http_unavailable_sources_have_structured_conflicts(boundary, state):
    ident = "unknown" if state == "absent" else "logs"
    if state == "disabled":
        source = boundary.services.resources.get("sources", "logs")
        source.enabled = False
        boundary.services.resources.save("sources", source)
    if state == "plugin_unavailable":
        boundary.services.plugins.collectorRegister = CollectorRegister()
    async with client_for(boundary) as client:
        response = await client.post(f"/api/sources/{ident}/collect", json={})
        schema = await client.get(f"/api/sources/{ident}/call-schema")
    assert response.status_code == schema.status_code == 409
    assert response.json()["error"]["code"] == "target_unavailable"
    assert boundary.collector.calls == []


@pytest.mark.parametrize("status", ["success", "empty", "filtered_empty", "failed", "missing", "timeout"])
async def test_http_preserves_result_status_without_retries(boundary, status):
    boundary.collector.missing = status == "missing"
    arguments = {"setters": {"fields": []}} if status == "filtered_empty" else {
        "options": {"mode": status if status != "missing" else "success"},
    }
    async with client_for(boundary) as client:
        response = await client.post("/api/sources/logs/collect", json=arguments)
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert response.json()["source_id"] == "logs"
    assert len(boundary.collector.calls) == 1
    assert boundary.collector.cleaned.is_set()


async def test_public_call_works_without_agent_or_shell_and_inside_workspace_write_lock(boundary):
    scheduler = ToolScheduler(4)
    boundary.services.agent = SimpleNamespace(scheduler=scheduler)
    async with scheduler.acquire("exclusive"), client_for(boundary) as client:
        response = await asyncio.wait_for(
            client.post("/api/sources/logs/collect", json={}), timeout=1,
        )
        assert response.json()["status"] == "success"
        assert scheduler.status["writing"] == 1 and scheduler.status["queued"] == 0


async def test_http_task_cancellation_reaches_collector_and_does_not_retry(boundary):
    source = boundary.services.resources.get("sources", "logs")
    source.timeout = 10
    boundary.services.resources.save("sources", source)
    async with client_for(boundary) as client:
        request = asyncio.create_task(client.post(
            "/api/sources/logs/collect", json={"options": {"mode": "timeout"}},
        ))
        await asyncio.wait_for(boundary.collector.started.wait(), timeout=1)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
    assert len(boundary.collector.calls) == 1
    assert boundary.collector.cleaned.is_set()


def test_cli_calls_http_schema_and_collection_with_server_deadline(boundary, tmp_path, monkeypatch):
    requests = []
    client_class = httpx.Client
    backend = TestClient(boundary.app)

    def forward(request):
        requests.append(request)
        response = backend.request(
            request.method, request.url.path, content=request.content,
            headers={"content-type": "application/json"},
        )
        return httpx.Response(response.status_code, json=response.json())

    monkeypatch.setattr(cli.httpx, "Client", lambda **kwargs: client_class(
        **kwargs, transport=httpx.MockTransport(forward),
    ))
    arguments = tmp_path / "arguments.json"
    arguments.write_text(json.dumps({"setters": {"fields": []}}), encoding="utf-8")
    runner = CliRunner()
    try:
        schema = runner.invoke(cli.app, ["collect-schema", "logs", "--api-url", "http://test"])
        result = runner.invoke(cli.app, [
            "collect", "logs", "--arguments", str(arguments), "--api-url", "http://test",
        ])
    finally:
        backend.close()
    assert schema.exit_code == result.exit_code == 0, (schema.output, result.output)
    assert json.loads(schema.stdout)["type"] == "object"
    assert json.loads(result.stdout)["status"] == "filtered_empty"
    assert [(item.method, item.url.path) for item in requests] == [
        ("GET", "/api/sources/logs/call-schema"), ("POST", "/api/sources/logs/collect"),
    ]
    assert requests[-1].extensions["timeout"] == {
        "connect": 30.0, "read": None, "write": 30.0, "pool": 30.0,
    }
    assert len(boundary.collector.calls) == 1
    assert boundary.collector.calls[0][1]["fields"] == []


@pytest.mark.parametrize("body", ["[]", "null", "not-json", "{\"secret\":"])
def test_cli_rejects_malformed_argument_files_before_http(tmp_path, monkeypatch, body):
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
def test_cli_validates_source_id_before_building_url(monkeypatch, command):
    def unexpected(**kwargs):
        raise AssertionError("Invalid source ID must not reach HTTP")

    monkeypatch.setattr(cli.httpx, "Client", unexpected)
    result = CliRunner().invoke(cli.app, [command, "../workflows/trigger"])
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "invalid_argument"


@pytest.mark.parametrize("failure", ["transport", "validation", "unavailable"])
def test_cli_surfaces_http_failures_without_retries(monkeypatch, failure):
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
