import asyncio
import json
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from logagent.agent.service import AgentService
from logagent.errors import LogAgentError
from logagent.interaction.app import create_app
from logagent.interaction.errors import status_for_code
from tests.agent.test_admission import GatedModel


class FakeAgent:
    def __init__(self):
        self.config = SimpleNamespace(model_dump=lambda mode="json": {"read_lines": 200})
        self.items = {}
        self.counter = 0

    async def list_sessions(self):
        return list(self.items.values())

    async def create_session(self, **kwargs):
        self.counter += 1
        item = {"session_id": f"agent-{self.counter}", "branch_id": "branch-1",
                "model": kwargs.get("model"), "workflow_session_id": kwargs.get("workflow_session_id"),
                "created_at": "now", "updated_at": "now", "status": "completed", "turn_id": None}
        self.items[item["session_id"]] = item
        return item

    async def get_session(self, session_id):
        if session_id not in self.items:
            raise LogAgentError("session_not_found", "Agent session 不存在")
        return self.items[session_id]

    async def submit(self, session_id, text, *, request_id):
        return {"session_id": session_id, "turn_id": "turn-1", "deduplicated": False}

    async def cancel(self, session_id):
        return self.items[session_id]

    async def events(self, session_id, *, after=0):
        return [{"id": 1, "type": "session.created", "created_at": "now"}]


class Lifecycle:
    def __init__(self):
        self.services = SimpleNamespace(
            agent=FakeAgent(), plugins=SimpleNamespace(generation=1),
        )

    async def start(self):
        return self.services

    async def shutdown(self):
        pass

    async def update_plugin_setting(self, plugin_id, enabled):
        self.setting = (plugin_id, enabled)
        return SimpleNamespace(model_dump=lambda mode="json": {"registered": [], "errors": []})


def test_agent_session_message_and_replay_endpoints():
    with TestClient(create_app(Lifecycle())) as client:
        created = client.post("/api/agents/sessions", json={"model": "mock"})
        assert created.status_code == 201
        session_id = created.json()["session_id"]
        accepted = client.post(
            f"/api/agents/sessions/{session_id}/messages",
            json={"request_id": "r1", "text": "hello"},
        )
        assert accepted.status_code == 202
        replay = client.get(f"/api/agents/sessions/{session_id}/events", params={"after": 0})
        assert replay.status_code == 200
        assert "session.created" in replay.text


def test_missing_sse_session_returns_structured_error_before_streaming():
    with TestClient(create_app(Lifecycle())) as client:
        response = client.get("/api/agents/sessions/missing/events")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_not_found"


def test_agent_conflict_codes_are_http_409():
    for code in ("request_conflict", "session_conflict", "file_conflict", "replace_conflict"):
        assert status_for_code(code) == 409


def test_agent_tool_switch_uses_lifecycle_reload_boundary():
    owner = Lifecycle()
    with TestClient(create_app(owner)) as client:
        response = client.put("/api/agents/tools/agent_shell", json={"enabled": False})
    assert response.status_code == 200
    assert owner.setting == ("agent_shell", False)


async def test_real_sse_disconnect_keeps_turn_running_and_replays_its_completion(tmp_path):
    model = GatedModel(responses=[AIMessage(content="answer after disconnect")])
    service = AgentService(
        tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model,
    )
    owner = Lifecycle()
    owner.services.agent = service
    app = create_app(owner)
    try:
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            created = await client.post("/api/agents/sessions", json={"model": "test"})
            assert created.status_code == 201
            sid = created.json()["session_id"]
            accepted = await client.post(f"/api/agents/sessions/{sid}/messages", json={
                "request_id": "r1", "text": "hello",
            })
            assert accepted.status_code == 202
            await asyncio.wait_for(model.entered.wait(), 1)
            disconnected = asyncio.Event()
            chunks = []
            request_received = False

            async def receive():
                nonlocal request_received
                if not request_received:
                    request_received = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                await disconnected.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] == "http.response.body" and b"data:" in message.get("body", b""):
                    chunks.append(message["body"].decode())
                    disconnected.set()

            await asyncio.wait_for(app({
                "type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"},
                "http_version": "1.1", "method": "GET", "scheme": "http",
                "path": f"/api/agents/sessions/{sid}/events", "root_path": "",
                "query_string": b"", "headers": [], "client": ("test", 1),
                "server": ("test", 80),
            }, receive, send), 2)
            assert chunks and disconnected.is_set()
            assert not service.sessions[sid].task.done()
            cursor = max(int(line[4:]) for chunk in chunks for line in chunk.splitlines()
                         if line.startswith("id: "))
            model.release.set()
            result = await service.wait(accepted.json()["turn_id"])
            assert result["status"] == "completed"
            replay = await client.get(f"/api/agents/sessions/{sid}/events", headers={
                "Last-Event-ID": str(cursor),
            })
            assert replay.status_code == 200
            events = [json.loads(line[6:]) for line in replay.text.splitlines()
                      if line.startswith("data: ")]
            assert events and all(event["id"] > cursor for event in events)
            assert events[-1]["type"] == "turn.completed"
            assert events[-1]["text"] == "answer after disconnect"
            assert not any(event["type"] == "turn.cancelled" for event in events)
    finally:
        await service.close()
