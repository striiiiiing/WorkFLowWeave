"""HTTP 交互适配层测试。

向真实 FastAPI 应用注入内存资源、Workflow、SessionView 与生命周期替身，
通过 TestClient 验证 CRUD、触发/取消/恢复、版本查询及插件/健康/reload 路由。
断言参数边界、服务委派、HTTP 状态映射与异常脱敏；不启动真实工作流或存储。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from logagent.errors import LogAgentError
from logagent.interaction.app import create_app
from logagent.models import (
    CapabilityDescription,
    DiscoveryReport,
    HealthReport,
    MCPHealthReport,
    PhaseContent,
    SessionRecord,
)


class MemoryResources:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {
            "sources": {},
            "setters": {},
            "mcp_servers": {},
            "ai": {},
            "channels": {},
            "workflows": {},
        }

    def get(self, kind: str, ident: str):
        value = self.values[kind].get(ident)
        return value.model_copy(deep=True) if value is not None else None

    def list(self, kind: str):
        return [self.values[kind][key].model_copy(deep=True) for key in sorted(self.values[kind])]

    def save(self, kind: str, resource, *, mode: str = "upsert"):
        exists = resource.id in self.values[kind]
        if mode == "create" and exists:
            raise LogAgentError("already_exists", "resource already exists")
        if mode == "replace" and not exists:
            raise LogAgentError("not_found", "resource does not exist")
        stored = resource.model_copy(deep=True)
        self.values[kind][resource.id] = stored
        return stored.model_copy(deep=True)

    def delete(self, kind: str, ident: str) -> None:
        if ident not in self.values[kind]:
            raise LogAgentError("not_found", "resource does not exist")
        del self.values[kind][ident]

    def save_many(self, resources, *, mode: str = "upsert"):
        for kind, values in resources.items():
            for value in values:
                self.save(kind, value, mode=mode)


class Workflow:
    def __init__(self, resources: MemoryResources) -> None:
        self.resources = resources
        self.saved = []
        self.triggered = []
        self.recovered = []
        self.cancelled = []

    async def save(self, workflow, *, mode: str):
        self.saved.append((workflow, mode))
        return self.resources.save("workflows", workflow, mode=mode)

    async def trigger(self, workflow):
        self.triggered.append(workflow)
        return "session-1"

    async def resume(self, session_id: str):
        self.recovered.append(session_id)
        return session_id

    async def cancel(self, session_id: str):
        self.cancelled.append(session_id)
        return True


class Sessions:
    def __init__(self) -> None:
        self.calls = []
        self.record = SessionRecord(
            session_id="session-1",
            workflow_id="daily",
            workflow_name="每日日报",
            version=1,
            status="completed",
            stage="finish",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            finished_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            artifacts=[],
            snapshot_availability="available",
        )

    async def list_sessions(self, workflow_id=None, **kwargs):
        self.calls.append(("list", workflow_id, kwargs))
        if workflow_id not in (None, self.record.workflow_id):
            return []
        return [self.record]

    async def get_session(self, session_id: str, *, version: int | None = None):
        self.calls.append(("get", session_id, version))
        if session_id != self.record.session_id:
            raise LogAgentError("not_found", "session does not exist")
        return self.record

    async def get_phase_content(self, session_id: str, stage: str, *, version: int):
        self.calls.append(("phase", session_id, stage, version))
        return PhaseContent(
            session_id=session_id,
            version=version,
            stage=stage,
            availability="available",
            content={"stage": stage},
        )


class Registry:
    def __init__(self, item: CapabilityDescription | None = None) -> None:
        self.item = item

    def describe(self):
        return [self.item] if self.item is not None else []


class MCPProbe:
    async def probe(self, scope, server):
        if server not in scope:
            raise LogAgentError("mcp_out_of_scope", "MCP 服务不存在")
        return MCPHealthReport(
            server=server,
            status="healthy",
            checked_at=datetime(2026, 1, 1, tzinfo=UTC),
            latency_ms=2.5,
            tool_count=1,
        )

    def status(self, scope):
        return []


class Lifecycle:
    def __init__(self) -> None:
        self.resources = MemoryResources()
        self.workflow = Workflow(self.resources)
        self.session_view = Sessions()
        capability = CapabilityDescription(
            kind="collector",
            name="mock",
            description="Offline mock collector",
            plugin="builtin",
            capabilities=["collection"],
            options_schema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "description": "Mock result mode",
                    }
                },
                "additionalProperties": False,
            },
            setters_schema={"type": "object", "additionalProperties": False},
            fields=["message"],
            count_unit="records",
        )
        self.services = SimpleNamespace(
            resources=self.resources,
            workflow=self.workflow,
            session_view=self.session_view,
            collectors=SimpleNamespace(mcp=MCPProbe()),
            plugins=SimpleNamespace(
                collectorRegister=Registry(capability),
                channelRegister=Registry(),
                toolRegister=Registry(),
            ),
        )
        self.started = 0
        self.shutdowns = 0
        self.reloads = []
        self.health_report = HealthReport(
            status="ready",
            accepting_runs=True,
            checked_at=datetime(2026, 1, 1, tzinfo=UTC),
            components=[],
        )

    async def start(self):
        self.started += 1
        return self.services

    async def shutdown(self) -> None:
        self.shutdowns += 1

    async def health(self):
        return self.health_report

    async def reload(self, scope: str):
        self.reloads.append(scope)
        if scope == "plugins":
            return DiscoveryReport()
        return None


def _client(lifecycle: Lifecycle, *, raise_server_exceptions: bool = True) -> TestClient:
    return TestClient(
        create_app(lifecycle),
        raise_server_exceptions=raise_server_exceptions,
    )


def _resource_payloads() -> dict[str, dict]:
    return {
        "sources": {"id": "source", "call": {"kind": "cli", "mode": "argv", "executable": "printf", "argv": ["%s", "example"]}},
        "ai": {"id": "ai", "provider": "mock", "models": {"model": {}}},
        "channels": {"id": "channel", "channel": "mock", "options": {}},
        "workflows": {
            "id": "daily",
            "sources": ["source"],
            "analyses": [{"user_prompt": "analyze input", "id": "task", "ai": "ai", "model": "model"}],
        },
    }


def test_lifespan_and_successful_resource_trigger_session_flow():
    lifecycle = Lifecycle()
    with _client(lifecycle) as client:
        assert lifecycle.started == 1
        for kind, payload in _resource_payloads().items():
            created = client.post(f"/api/{kind}", json=payload)
            assert created.status_code == 201, created.text
            assert created.json()["id"] == payload["id"]
            assert client.get(f"/api/{kind}").json()[0]["id"] == payload["id"]
            assert client.get(f"/api/{kind}/{payload['id']}").json()["id"] == payload["id"]
            replaced = client.put(f"/api/{kind}/{payload['id']}", json=payload)
            assert replaced.status_code == 200, replaced.text

        triggered = client.post(
            "/api/workflows/trigger",
            json={"workflow_id": "daily"},
        )
        assert triggered.status_code == 202
        assert triggered.json() == {"session_id": "session-1"}
        assert triggered.headers["location"] == "/api/sessions/session-1"
        assert lifecycle.workflow.triggered == ["daily"]
        assert [mode for _, mode in lifecycle.workflow.saved] == ["create", "replace"]
        snapshot_trigger = client.post(
            "/api/workflows/trigger",
            json={
                "snapshot": {
                    "workflow": _resource_payloads()["workflows"],
                    "sources": {"source": _resource_payloads()["sources"]},
                    "ai": {"ai": _resource_payloads()["ai"]},
                    "channels": {},
                    "created_at": "2026-01-01T00:00:00Z",
                }
            },
        )
        assert snapshot_trigger.status_code == 202
        assert not isinstance(lifecycle.workflow.triggered[-1], str)

        sessions = client.get(
            "/api/sessions",
            params={"workflow_id": "daily", "limit": 1, "offset": 0},
        )
        assert sessions.status_code == 200
        assert sessions.json()[0]["session_id"] == "session-1"
        assert client.get("/api/sessions/session-1", params={"version": 1}).status_code == 200
        phase = client.get("/api/sessions/session-1/phases/analyze", params={"version": 1})
        assert phase.status_code == 200
        assert phase.json()["content"] == {"stage": "analyze"}
        assert client.post("/api/sessions/session-1/recover").status_code == 202
        cancelled = client.post("/api/sessions/session-1/cancel")
        assert cancelled.json() == {"session_id": "session-1", "cancelled": True}
        assert lifecycle.workflow.recovered == ["session-1"]
        assert lifecycle.workflow.cancelled == ["session-1"]

        for kind, payload in _resource_payloads().items():
            assert client.delete(f"/api/{kind}/{payload['id']}").status_code == 204
            assert client.get(f"/api/{kind}/{payload['id']}").status_code == 409
    assert lifecycle.shutdowns == 1


def test_mcp_import_uses_server_name_and_hyphen():
    lifecycle = Lifecycle()
    with _client(lifecycle) as client:
        response = client.post(
            "/api/mcp_servers/import",
            json={
                "servers": {
                    "qqmusic-mcp": {
                        "type": "stdio",
                        "command": "qqmusic-mcp",
                        "args": ["stdio"],
                    }
                }
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()[0]["id"] == "qqmusic-mcp"
        saved = client.get("/api/mcp_servers").json()
        assert saved[0]["id"] == "qqmusic-mcp"
        assert saved[0]["command"] == "qqmusic-mcp"

        duplicate = client.post(
            "/api/mcp_servers/import",
            json={"servers": {"qqmusic-mcp": {"command": "other"}}},
        )
        assert duplicate.status_code == 409
        assert client.get("/api/mcp_servers").json() == saved


def test_mcp_server_probe_returns_health_report():
    lifecycle = Lifecycle()
    with _client(lifecycle) as client:
        created = client.post(
            "/api/mcp_servers",
            json={"id": "demo", "transport": "stdio", "command": "server"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["health_check_enabled"] is False
        assert created.json()["health_check_interval_minutes"] == 30
        updated = client.put(
            "/api/mcp_servers/demo",
            json={
                **created.json(),
                "health_check_enabled": True,
                "health_check_interval_minutes": 10_000_001,
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["health_check_interval_minutes"] == 10_000_001
        response = client.post("/api/mcp_servers/demo/probe")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "healthy"
        assert response.json()["tool_count"] == 1


def test_transport_validation_rejects_unknown_fields_and_invalid_query_values():
    lifecycle = Lifecycle()
    with _client(lifecycle) as client:
        unknown = client.post(
            "/api/sources",
            json={**_resource_payloads()["sources"], "unexpected": True},
        )
        assert unknown.status_code == 422
        assert unknown.json()["error"]["code"] == "validation"
        assert any(
            issue["path"] == ["body", "unexpected"]
            for issue in unknown.json()["error"]["details"]["errors"]
        )

        assert client.get("/api/sessions", params={"limit": 0}).status_code == 422
        assert client.get("/api/sessions", params={"unexpected": "field"}).status_code == 422
        assert client.get("/api/sessions", params={"status": "unknown"}).status_code == 422
        assert client.get("/api/sessions", params={"session_id": "not-valid!"}).status_code == 422
        assert client.get("/api/sessions", params={"workflow_name": ""}).status_code == 422
        assert (
            client.get(
                "/api/sessions",
                params={"after": "2026-01-01T00:00:00"},
            ).status_code
            == 422
        )
        assert client.get("/api/sessions/session-1/phases/analyze").status_code == 422
        assert client.get("/api/sessions/not-valid!").status_code == 422


def test_session_fields_are_forwarded_and_names_returned_in_list_and_detail():
    lifecycle = Lifecycle()
    with _client(lifecycle) as client:
        response = client.get("/api/sessions", params={
            "workflow_name": "日报", "session_id": "session-1", "status": "completed",
            "limit": 5, "offset": 1,
        })
        assert response.status_code == 200
        assert response.json()[0]["workflow_name"] == "每日日报"
        assert lifecycle.session_view.calls[-1] == ("list", None, {
            "workflow_name": "日报", "session_id": "session-1", "status": "completed",
            "limit": 5, "offset": 1, "after": None, "before": None,
        })
        assert client.get("/api/sessions/session-1").json()["workflow_name"] == "每日日报"


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        ("invalid_config", 422),
        ("invalid_argument", 422),
        ("validation", 422),
        ("reference_conflict", 409),
        ("already_exists", 409),
        ("not_found", 409),
        ("session_exists", 409),
        ("session_not_found", 409),
        ("version_not_found", 409),
        ("plugin_reload_conflict", 409),
        ("capacity_exhausted", 429),
        ("not_ready", 503),
        ("shutdown", 503),
        ("configuration_unavailable", 503),
        ("storage_failed", 503),
        ("storage", 503),
        ("checkpoint", 503),
        ("checkpoint_unavailable", 503),
    ],
)
def test_structured_error_status_mapping(code: str, expected_status: int):
    lifecycle = Lifecycle()

    def fail(*_):
        raise LogAgentError(code, "public error")

    lifecycle.resources.get = fail
    with _client(lifecycle, raise_server_exceptions=False) as client:
        response = client.get("/api/sources/missing")
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == code


def test_unknown_error_is_redacted_and_logged(caplog):
    lifecycle = Lifecycle()

    def fail(*_):
        raise RuntimeError("secret-token-and-path")

    lifecycle.resources.get = fail
    with caplog.at_level(logging.ERROR, logger="logagent.interaction"):
        with _client(lifecycle, raise_server_exceptions=False) as client:
            response = client.get("/api/sources/missing")
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "服务内部错误",
            "details": {},
        }
    }
    assert "secret-token-and-path" not in response.text
    assert "unhandled_interaction_error" in caplog.text


def test_plugins_health_reload_and_unavailable_health():
    lifecycle = Lifecycle()
    with _client(lifecycle) as client:
        plugins = client.get("/api/plugins")
        assert plugins.status_code == 200
        assert plugins.json()[0]["name"] == "mock"
        assert plugins.json()[0]["options_schema"]["properties"]["mode"][
            "description"
        ] == "Mock result mode"

        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ready"

        resources = client.post("/api/reload", params={"scope": "resources"})
        assert resources.status_code == 200
        assert resources.json() == {"scope": "resources", "report": None}
        plugin_reload = client.post("/api/reload", params={"scope": "plugins"})
        assert plugin_reload.status_code == 200
        assert plugin_reload.json()["report"]["errors"] == []
        assert lifecycle.reloads == ["resources", "plugins"]

        lifecycle.health_report = lifecycle.health_report.model_copy(
            update={"status": "unavailable", "accepting_runs": False}
        )
        assert client.get("/api/health").status_code == 503


def test_cron_preview_and_schedule_contract():
    lifecycle = Lifecycle()
    with _client(lifecycle) as client:
        preview = client.post("/api/workflows/cron/preview", json={
            "expression": "0 9 * * 0", "timezone": "Asia/Shanghai",
        })
        assert preview.status_code == 200
        value = preview.json()
        assert "星期一" in value["description"]
        assert value["timezone"] == "Asia/Shanghai"
        assert datetime.fromisoformat(value["next_run_at"]).tzinfo is not None
        assert client.post("/api/workflows/cron/preview", json={
            "expression": "not cron",
        }).status_code == 422
        assert client.post("/api/workflows/cron/preview", json={
            "expression": "0 9 * * *", "timezone": "Invalid/Zone",
        }).status_code == 422
        base = {"id": "daily", "sources": ["s"],
                "analyses": [{"user_prompt": "analyze input", "id": "a", "ai": "ai", "model": "model"}]}
        for field in ("cron", "interval_seconds", "cron_timezone"):
            assert client.post("/api/workflows", json={**base, field: None}).status_code == 422
        for schedule in (
            {"type": "at", "at": "2027-01-01T09:00:00+08:00"},
            {"type": "every", "every_seconds": 2.5},
            {"type": "cron", "expression": "0 9 * * *"},
        ):
            response = client.post("/api/workflows", json={**base, "schedule": schedule})
            assert response.status_code == 201
            assert response.json()["schedule"]["type"] == schedule["type"]
            client.delete("/api/workflows/daily")
