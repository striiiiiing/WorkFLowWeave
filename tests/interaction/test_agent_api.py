"""HTTP/SSE Agent API contract tests."""

import asyncio
import json
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from workflowweave.agent.commands import CommandDispatcher
from workflowweave.channel.web import WebChannel
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.interaction.app import create_app
from workflowweave.interaction.errors import status_for_code
from workflowweave.interaction.fastapi.agent import create_agent_service
from tests.agent.helpers import ScriptedModel
from tests.agent.test_admission import GatedModel


class FakeAgent:
    def __init__(self):
        self.config = SimpleNamespace(model_dump=lambda mode="json": {"read_lines": 200})
        self.items = {}
        self.counter = 0
        self.submissions = []

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
            raise WorkFLowWeaveError("session_not_found", "Agent session 不存在")
        return self.items[session_id]

    async def submit(self, session_id, text, *, request_id):
        self.submissions.append((session_id, text, request_id))
        return {"session_id": session_id, "turn_id": "turn-1", "deduplicated": False}

    async def append(self, session_id, text, *, request_id):
        return {"session_id": session_id, "turn_id": "turn-1", "deduplicated": False}

    async def compact(self, session_id):
        return {"session_id": session_id, "turn_id": "turn-1", "deduplicated": False}

    async def fork(self, session_id, **kwargs):
        return await self.create_session(model=kwargs.get("model"))

    async def cancel(self, session_id):
        return self.items[session_id]

    async def events(self, session_id, *, after=0):
        return [{"id": 1, "type": "session.created", "created_at": "now"}]

    async def wait_events(self, session_id, *, after=0, wait_seconds=0.5):
        return await self.events(session_id, after=after)

    async def wait(self, turn_id):
        return {"turn_id": turn_id, "status": "completed"}


class Lifecycle:
    def __init__(self):
        self.services = SimpleNamespace(
            agent=FakeAgent(), plugins=SimpleNamespace(generation=1),
        )
        self.services.agent_channel = CommandDispatcher(self.services.agent)
        self.services.channels = _TestChannelManager(self.services)

    def use_agent(self, agent):
        self.services.agent = agent
        self.services.agent_channel = CommandDispatcher(agent, self.services.session_view if hasattr(self.services, "session_view") else None)

    async def start(self):
        return self.services

    async def shutdown(self):
        pass

    async def update_plugin_setting(self, plugin_id, enabled):
        self.setting = (plugin_id, enabled)
        return SimpleNamespace(model_dump=lambda mode="json": {"registered": [], "errors": []})


class _TestChannelManager:
    """Expose only the HTTP transport boundary in isolated route tests."""

    def __init__(self, services):
        self.services = services
        self.web_channel = WebChannel(self)

    @property
    def agent_channel(self):
        return self.services.agent_channel

    async def dispatch_web(self, command):
        return await self.agent_channel.dispatch(command)


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


def test_web_channel_uses_explicit_message_action_for_slash_prefixed_text():
    owner = Lifecycle()
    with TestClient(create_app(owner)) as client:
        session_id = client.post("/api/agents/sessions", json={}).json()["session_id"]
        response = client.post("/api/channels/web/commands", json={
            "channel": "web", "session": session_id, "request_id": "literal",
            "action": "message", "text": "/stop",
        })
    assert response.status_code == 202
    assert response.json()["kind"] == "turn"
    assert owner.services.agent.submissions == [(session_id, "/stop", "literal")]


def test_agent_conflict_codes_are_http_409():
    for code in ("request_conflict", "session_conflict", "file_conflict", "replace_conflict"):
        assert status_for_code(code) == 409


def test_agent_tool_switch_uses_lifecycle_reload_boundary():
    owner = Lifecycle()
    with TestClient(create_app(owner)) as client:
        response = client.put("/api/agents/tools/agent_shell", json={"enabled": False})
    assert response.status_code == 200
    assert owner.setting == ("agent_shell", False)


async def test_topic_patch_is_persisted_and_rejects_ambiguous_updates(tmp_path):
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime",
                           model_provider=lambda _: ScriptedModel(responses=[]))
    owner = Lifecycle()
    owner.use_agent(service)
    app = create_app(owner)
    try:
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            created = await client.post("/api/agents/sessions", json={"model": "test"})
            path = f"/api/agents/sessions/{created.json()['session_id']}"
            changed = await client.patch(path, json={"title": "  告警复盘  "})
            assert changed.status_code == 200
            assert changed.json()["title"] == "告警复盘"
            assert (await client.get(path)).json()["title"] == "告警复盘"
            history = (await client.get(f"{path}/history")).json()
            assert history[-1]["type"] == "session.title.changed"
            for payload in ({}, {"title": "new", "model": "test"}, {"title": " "}):
                rejected = await client.patch(path, json=payload)
                assert rejected.status_code == 422
            assert (await client.get(path)).json()["title"] == "告警复盘"
    finally:
        await service.close()


async def test_real_sse_disconnect_keeps_turn_running_and_replays_its_completion(tmp_path):
    model = GatedModel(responses=[AIMessage(content="answer after disconnect")])
    service = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model,
    )
    owner = Lifecycle()
    owner.use_agent(service)
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
            assert not service.turns.current(sid).task.done()
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


async def test_files_enforce_conditional_writes_and_preserve_external_changes(tmp_path):
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime")
    owner = Lifecycle()
    owner.use_agent(service)
    app = create_app(owner)
    try:
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            sid = (await client.post("/api/agents/sessions", json={})).json()["session_id"]
            url = f"/api/agents/file?session_id={sid}&path=Memory/test.md"
            body = {"mode": "overwrite", "content": "first\nsecond\nthird\n"}
            assert (await client.put(url, json=body)).status_code == 428
            created = await client.put(url, json=body, headers={"If-None-Match": "*"})
            assert created.status_code == 200
            version = created.headers["etag"]
            page = await client.get(url + "&offset=1&limit=1")
            assert page.status_code == 200, page.text
            assert page.headers["etag"] == version
            assert page.json()["content"] == "second\n" and page.json()["next_offset"] == 2
            changed = await client.put(url, json={**body, "content": "external"}, headers={"If-Match": version})
            assert changed.status_code == 200
            stale = await client.put(url, json={**body, "content": "draft"}, headers={"If-Match": version})
            assert stale.status_code == 409
            assert (await client.get(url)).json()["content"] == "external"
            assert (await client.put(url, json=body, headers={"If-None-Match": "*"})).status_code == 409
            runtime = f"/api/agents/file?session_id={sid}&path=Runtime/self.json"
            info = await client.get(runtime)
            assert info.json()["readonly"] is True
            assert (await client.put(runtime, json=body, headers={"If-Match": info.headers["etag"]})).status_code == 403
    finally:
        await service.close()


async def test_slow_sse_consumer_does_not_block_turn_and_gets_terminal_racing_batch(tmp_path):
    model = GatedModel(responses=[AIMessage(content="completed independently")])
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model)
    owner = Lifecycle()
    owner.use_agent(service)
    app = create_app(owner)
    try:
        sid = (await service.create_session())["session_id"]
        turn = await service.submit(sid, "hello", request_id="r1")
        await asyncio.wait_for(model.entered.wait(), 1)
        app.state.services = owner.services
        paused, resume = asyncio.Event(), asyncio.Event()
        chunks = []
        request_received = False

        async def receive():
            nonlocal request_received
            if not request_received:
                request_received = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            if message["type"] == "http.response.body" and b"data:" in message.get("body", b""):
                chunks.append(message["body"].decode())
                paused.set()
                await resume.wait()

        async with app.router.lifespan_context(app):
            stream = asyncio.create_task(app({
                "type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"},
                "http_version": "1.1", "method": "GET", "scheme": "http", "root_path": "",
                "path": f"/api/agents/sessions/{sid}/events", "query_string": b"", "headers": [],
                "client": ("test", 1), "server": ("test", 80),
            }, receive, send))
            await asyncio.wait_for(paused.wait(), 1)
            model.release.set()
            assert (await asyncio.wait_for(service.wait(turn["turn_id"]), 2))["status"] == "completed"
            assert not stream.done()
            resume.set()
            await asyncio.wait_for(stream, 2)
            delivered = [json.loads(line[6:]) for chunk in chunks for line in chunk.splitlines() if line.startswith("data: ")]
            assert delivered[-1]["type"] == "turn.completed"
            assert [event["id"] for event in delivered] == list(range(1, len(delivered) + 1))
    finally:
        await service.close()


async def test_workflow_source_is_frozen_and_command_stop_has_independent_priority(tmp_path):
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    model = GatedModel(responses=[AIMessage(content="answer")])
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime", model_provider=lambda _: model)
    owner = Lifecycle()
    owner.services.agent = service
    record = SimpleNamespace(session_id="run-old", workflow_id="workflow", status="completed",
                             version=1, finished_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    owner.services.session_view = SimpleNamespace(
        list_sessions=AsyncMock(return_value=[record]), get_session=AsyncMock(return_value=record),
        get_phase_content=AsyncMock(return_value=SimpleNamespace(availability="available", content={"outputs": {"answer": "frozen"}})),
    )
    owner.services.agent_channel = CommandDispatcher(service, owner.services.session_view)
    app = create_app(owner)
    try:
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/api/agents/sessions", json={"workflow_id": "workflow"})
            assert created.status_code == 201
            sid = created.json()["session_id"]
            owner.services.session_view.get_phase_content.return_value.content = {"outputs": {"answer": "new run"}}
            source = (await client.get(f"/api/agents/sessions/{sid}/source")).json()
            assert source["workflow_session_id"] == "run-old" and source["input"]["outputs"]["answer"] == "frozen"
            rejected = await client.post("/api/agents/sessions", json={"workflow_session_id": "run-old", "workflow_result": "override"})
            assert rejected.status_code == 422
            accepted = await client.post("/api/agents/commands", json={"channel": "web", "session": sid, "text": "hello", "request_id": "r1", "priority": "conversation"})
            assert accepted.json()["kind"] == "turn"
            await asyncio.wait_for(model.entered.wait(), 1)
            await client.post("/api/agents/commands", json={"session": sid, "text": "/append more", "request_id": "r2"})
            stopped = await client.post("/api/agents/commands", json={"session": sid, "text": "/stop", "request_id": "r3", "priority": "stop"})
            assert stopped.json()["result"]["status"] == "cancelled"
            events = await service.events(sid)
            assert events[-1]["type"] == "turn.cancelled"
            assert any(event["type"] == "command.cancelled" for event in events)
            bad = await client.post("/api/agents/commands", json={"session": sid, "text": "/stop", "request_id": "r4", "priority": "conversation"})
            assert bad.status_code == 422
    finally:
        await service.close()
