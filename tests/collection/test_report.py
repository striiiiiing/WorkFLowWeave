"""Plugin report declarations survive the real collection boundary and archives."""
import pytest

from logagent.models import SourceConfig
from logagent.workflow import SessionStore, WorkflowService
from tests.collection.test_manager import CONTEXT, FunctionCollector, manager_for
from tests.workflow.helpers import AI, Channel, snapshot

REPORT = {"sections": [
    {"kind": "text", "title": "采集概况", "text": "本次有 **2** 条记录。"},
    {"kind": "metrics", "title": "数量", "items": [{"label": "告警", "value": 2, "unit": "条"}]},
    {"kind": "table", "title": "详情", "columns": ["内容", "数量"], "rows": [["错误", 2]]},
]}


async def test_report_is_validated_and_archived_with_original_version(tmp_path):
    async def collect(*args):
        return {"status": "success", "text": "original input", "count": 2, "report": REPORT}
    manager = await manager_for(tmp_path, FunctionCollector(collect))
    store = SessionStore(tmp_path / "runs.sqlite3")
    ai = AI()
    workflow = WorkflowService(manager, ai, Channel(), session_store=store)
    try:
        config = snapshot(channels=False)
        config.sources["source"].collector = "custom"
        await workflow.trigger(config, session_id="report")
        await workflow.wait("report")
        record = await workflow.get_session("report")
        content = await workflow.session_view.get_phase_content("report", "collect", version=record.version)
        assert content.content["collection"][0]["report"] == REPORT
        assert ai.calls[0][1].startswith("original input")
        assert "采集概况" not in ai.calls[0][1]
    finally:
        await workflow.shutdown()
        store.close()


@pytest.mark.parametrize("section", [
    {"kind": "html", "title": "bad", "text": "<script>bad</script>"},
    {"kind": "table", "title": "bad", "columns": ["one"], "rows": [[1, 2]]},
    {"kind": "metrics", "title": "bad", "items": [{"label": "number", "value": float("nan")}]},
])
async def test_invalid_report_is_an_explicit_plugin_output_error(tmp_path, section):
    async def collect(*args):
        return {"status": "success", "text": "text", "count": 1, "report": {"sections": [section]}}
    manager = await manager_for(tmp_path, FunctionCollector(collect))
    result = await manager.collect(SourceConfig(id="one", collector="custom"), CONTEXT)
    assert result.status == "failed" and result.error.code == "invalid_collector_output"
