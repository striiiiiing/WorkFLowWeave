from types import SimpleNamespace

from fastapi.testclient import TestClient

from logagent.errors import LogAgentError
from logagent.interaction.app import create_app
from logagent.interaction.errors import status_for_code


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
        self.services = SimpleNamespace(agent=FakeAgent())

    async def start(self):
        return self.services

    async def shutdown(self):
        pass


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
