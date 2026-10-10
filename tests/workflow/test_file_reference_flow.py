from tests.workflow.helpers import AI, Channel
from tests.workflow.test_input_processing import snapshot
from workflowweave.collection import CollectorManager, FileReferenceStore
from workflowweave.config import ResourceStore
from workflowweave.models import (
    AIConfig,
    CollectionResult,
    FileCall,
    SourceConfig,
    WorkflowDefinition,
)
from workflowweave.workflow.execution.runner import WorkflowRunner
from workflowweave.workflow.input_processing import process_input
from workflowweave.workflow.storage.facts import SessionStore


def test_file_json_and_plain_text_share_existing_processing_and_limits():
    config = snapshot(format="md", field=5)
    config.sources["first"].call = FileCall(file_type="text", path="notes.json")
    raw = {"text": '{"name":"abcdef","flag":false}'}
    result = CollectionResult(source_id="first", status="success", raw=raw)
    output, views = process_input(config, [result], [len])
    assert views[0].status == "success" and views[0].truncated
    assert "abc" in output and "abcdef" not in output
    assert result.raw == raw
    result = CollectionResult(source_id="first", status="success", raw={"text": "# title\r\nlog {broken}"})
    output, views = process_input(config, [result], [len])
    assert views[0].status == "success"
    assert output.endswith("# title\r\nlog {broken}")


async def test_workflow_new_runs_and_explicit_collection_rerun_read_fresh_files(tmp_path):
    files = FileReferenceStore(tmp_path / "data")
    files.create_text("example.txt", b"first")
    resources = ResourceStore(tmp_path / "resources.json")
    resources.save("sources", SourceConfig(id="source", call=FileCall(file_type="text", path="example.txt")))
    resources.save("ai", AIConfig(id="ai", provider="mock", models={"offline": {}}))
    resources.save("workflows", WorkflowDefinition(
        id="wf", sources=["source"],
        analyses=[{"id": "a", "ai": "ai", "model": "offline", "user_prompt": "analyze input"}],
    ))
    store = SessionStore(tmp_path / "sessions")
    workflow = WorkflowRunner(CollectorManager(None, files), AI(), Channel(), resources, session_store=store)
    try:
        sid = await workflow.trigger("wf")
        first = await workflow.wait(sid)
        assert first.status == "completed"
        assert first.collection[0].raw == {"text": "first"}
        entries = [entry async for entry in workflow.graph.aget_state_history(
            {"configurable": {"thread_id": sid}})]
        collect_entry = next(entry for entry in entries if entry.next == ("collect",))
        (files.root / "example.txt").write_bytes(b"second")
        await workflow.resume(sid, stage="analyze")
        retained = await workflow.wait(sid)
        assert retained.collection[0].raw == {"text": "first"}
        await workflow.resume(sid, stage="collect",
                              checkpoint_id=collect_entry.config["configurable"]["checkpoint_id"])
        rerun = await workflow.wait(sid)
        assert rerun.collection[0].raw == {"text": "second"}
        assert first.collection[0].raw == {"text": "first"}
        next_sid = await workflow.trigger("wf")
        new_run = await workflow.wait(next_sid)
        assert new_run.collection[0].raw == {"text": "second"}
    finally:
        await workflow.shutdown()
        store.close()
