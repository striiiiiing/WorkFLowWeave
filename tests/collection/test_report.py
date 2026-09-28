"""Raw collection archives retain their original version and representation."""

from logagent.collection.manager import CollectorManager
from logagent.workflow import SessionStore, WorkflowService
from tests.workflow.helpers import AI, Channel, snapshot


async def test_raw_cli_result_is_archived_separately_from_processed_input(tmp_path):
    store = SessionStore(tmp_path / "runs.sqlite3")
    ai = AI()
    workflow = WorkflowService(CollectorManager(None), ai, Channel(), session_store=store)
    try:
        config = snapshot(channels=False)
        config.sources["source"].call.executable = "printf"
        config.sources["source"].call.argv = ["%s", "raw,unprocessed"]
        config.workflow.input_processing.format = "csv"
        await workflow.trigger(config, session_id="raw-archive")
        result = await workflow.wait("raw-archive")
        original = await workflow.get_session("raw-archive")
        archived = await workflow.session_view.get_phase_content(
            "raw-archive", "collect", version=original.version,
        )
        assert result.collection[0].raw == {
            "stdout": "raw,unprocessed", "stderr": "", "exit_code": 0,
        }
        assert archived.content["collection"][0]["raw"] == result.collection[0].raw
        assert result.input_views[0].text != result.collection[0].raw["stdout"]
        assert ai.calls[0][1] == result.shared_input
    finally:
        await workflow.shutdown()
        store.close()
