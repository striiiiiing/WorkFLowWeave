import sys
from pathlib import Path

import pytest

from tests.workflow.helpers import AI, Channel, snapshot
from workflowweave.collection.manager import CollectorManager
from workflowweave.config.store import ResourceStore
from workflowweave.mcp import MCPRuntime, SDKConnector
from workflowweave.models import (
    AIConfig,
    CollectionContext,
    MCPServerConfig,
    SourceConfig,
    WorkflowDefinition,
)
from workflowweave.workflow.execution.runner import WorkflowRunner
from workflowweave.workflow.storage.facts import SessionStore


async def test_cli_workflow_archives_raw_result_and_processing_view(tmp_path):
    marker = tmp_path / "calls.txt"
    resources = ResourceStore(tmp_path / "resources.json")
    resources.save("sources", SourceConfig(id="source", call={
        "kind": "cli", "mode": "argv", "executable": sys.executable,
        "argv": ["-c", f"from pathlib import Path; p=Path({str(marker)!r}); p.write_text('x'); print('{{}}')"],
    }))
    resources.save("ai", AIConfig(id="ai", provider="mock", models={"offline": {}}))
    resources.save("workflows", WorkflowDefinition(id="wf", sources=["source"],
        analyses=[{"user_prompt": "analyze input", "id": "a", "ai": "ai", "model": "offline"}], input_processing={"format": "csv"}))
    store = SessionStore(tmp_path / "sessions")
    workflow = WorkflowRunner(CollectorManager(None), AI(), Channel(), resources, session_store=store)
    try:
        sid = await workflow.trigger("wf")
        result = await workflow.wait(sid)
        assert result.collection[0].status == "success"
        assert result.input_views[0].status == "failed"
        assert marker.read_text() == "x"
    finally:
        await workflow.shutdown()


async def test_successful_workflow_uses_separate_views_and_no_counts(tmp_path):
    from tests.workflow.helpers import Collector
    store = SessionStore(tmp_path / "sessions")
    ai = AI()
    service = WorkflowRunner(Collector(), ai, Channel(), session_store=store)
    try:
        sid = await service.trigger(snapshot(channels=False))
        result = await service.wait(sid)
        assert result.status == "completed"
        assert result.collection[0].raw["stdout"] == "original data"
        assert result.input_views[0].text == result.shared_input
        assert "count" not in result.model_dump()["collection"][0]
        assert all(call[1] == result.shared_input for call in ai.calls)
    finally:
        await service.shutdown()


@pytest.mark.parametrize("explicit_context", [False, True])
async def test_mcp_workflow_and_collect_rerun_use_frozen_server_bindings(tmp_path, explicit_context):
    resources = ResourceStore(tmp_path / "resources.json")
    server = MCPServerConfig(
        id="inspection", transport="stdio", command=sys.executable,
        args=[str(Path(__file__).parents[1] / "mcp/stdio_server.py")],
    )
    resources.save("mcp_servers", server)
    resources.save("sources", SourceConfig(id="source", call={
        "kind": "mcp", "server": "inspection", "tool": "echo",
        "arguments": {"value": "workflow MCP", "count": 0},
    }))
    resources.save("ai", AIConfig(id="ai", provider="mock", models={"offline": {}}))
    resources.save("workflows", WorkflowDefinition(
        id="wf", sources=["source"], analyses=[{
            "id": "a", "ai": "ai", "model": "offline", "user_prompt": "analyze input",
        }],
    ))
    runtime = MCPRuntime(SDKConnector(None), cache_dir=tmp_path / "mcp-cache")
    workflow = WorkflowRunner(
        CollectorManager(runtime), AI(), Channel(), resources,
        session_store=SessionStore(tmp_path / "sessions"),
    )
    context = CollectionContext("wf", "run") if explicit_context else None
    try:
        await workflow.trigger("wf", session_id="run", context=context)
        first = await workflow.wait("run")
        assert first.status == "completed"
        assert first.collection[0].raw["structuredContent"] == {"value": "workflow MCP", "count": 0}
        if context is not None:
            assert not context.mcp_servers
        resources.save("mcp_servers", server.model_copy(update={"command": "/missing-new-command"}))
        await workflow.resume("run", stage="collect", context=context)
        second = await workflow.wait("run")
        assert second.status == "completed"
        assert second.collection[0].raw == first.collection[0].raw
    finally:
        await workflow.shutdown()
        workflow.session_store.close()
