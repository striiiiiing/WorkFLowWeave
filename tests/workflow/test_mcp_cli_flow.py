import sys

from workflowweave.collection.manager import CollectorManager
from workflowweave.config.store import ResourceStore
from workflowweave.models import AIConfig, SourceConfig, WorkflowDefinition
from workflowweave.workflow.execution.runner import WorkflowRunner
from workflowweave.workflow.storage.facts import SessionStore
from tests.workflow.helpers import AI, Channel, snapshot


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
