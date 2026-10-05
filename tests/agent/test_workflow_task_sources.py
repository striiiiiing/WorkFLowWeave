"""Agent source endpoints read frozen current-runtime task and final archives."""

import httpx
import pytest

from logagent.agent.service import AgentService
from logagent.interaction.app import create_app
from logagent.models import FanInConfig
from logagent.workflow.execution.runner import WorkflowRunner
from tests.interaction.test_agent_api import Lifecycle
from tests.workflow.helpers import AI, Channel, Collector, snapshot


@pytest.mark.parametrize("task_id", ["first", "final", None])
async def test_http_session_creation_reads_selected_workflow_source(tmp_path, task_id):
    agent = AgentService(tmp_path / "workspace", tmp_path / "agent")
    workflow = WorkflowRunner(Collector(), AI(), Channel(), database=tmp_path / "runs.sqlite3")
    snap = snapshot(tasks=("first",), channels=False, fan_in=FanInConfig())
    try:
        result = await workflow.wait(await workflow.trigger(snap, session_id="run"))
        owner = Lifecycle()
        owner.services.session_view = workflow.session_view
        owner.use_agent(agent)
        app = create_app(owner)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            response = await client.post("/api/agents/sessions", json={
                "workflow_session_id": "run", "task_id": task_id,
            })
        assert response.status_code == 201, response.text
        view = response.json()
        assert view["workflow_task_id"] == task_id
        assert view["session_kind"] == ("workflow_subtask" if task_id else "workflow_continue")
        source = await agent.source(view["session_id"])
        assert source["workflow_session_id"] == "run"
        if task_id is None:
            assert source["input"]["outputs"] == result.outputs
        else:
            expected = result.analyses[0].text if task_id == "first" else result.outputs["final"]
            assert source["input"]["text"] == expected
    finally:
        await workflow.shutdown()
        await agent.close()


async def test_task_source_rejects_missing_result_or_source_override(tmp_path):
    agent = AgentService(tmp_path / "workspace", tmp_path / "agent")
    workflow = WorkflowRunner(Collector(), AI(fail={"second"}), Channel(),
                              database=tmp_path / "runs.sqlite3")
    try:
        await workflow.wait(await workflow.trigger(snapshot(channels=False), session_id="run"))
        owner = Lifecycle()
        owner.services.session_view = workflow.session_view
        owner.use_agent(agent)
        cases = [
            ({"task_id": "first"}, "invalid_argument"),
            ({"workflow_session_id": "run", "task_id": "second"}, "workflow_result_unavailable"),
            ({"workflow_session_id": "run", "task_id": "missing"}, "workflow_result_unavailable"),
            ({"workflow_session_id": "run", "workflow_result": "override"}, "invalid_argument"),
        ]
        app = create_app(owner)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            for payload, code in cases:
                response = await client.post("/api/agents/sessions", json=payload)
                assert response.status_code >= 400
                assert response.json()["error"]["code"] == code
        assert not agent.sessions
    finally:
        await workflow.shutdown()
        await agent.close()
