"""真实业务存档的名称投影与分页前字段过滤，不访问外部服务。"""

from datetime import UTC, datetime, timedelta

import pytest

from workflowweave.models import BackupPolicy
from workflowweave.workflow.execution.runner import WorkflowRunner
from workflowweave.workflow.storage.facts import SessionStore
from workflowweave.workflow.storage.sessions import SessionView
from tests.workflow.helpers import AI, Channel, Collector, snapshot


@pytest.mark.parametrize("backup_enabled", [True, False])
async def test_name_is_frozen_at_creation_and_survives_expiry_and_reopen(tmp_path, backup_enabled):
    path = tmp_path / "sessions.sqlite3"
    workflow = WorkflowRunner(Collector(), AI(), Channel(), database=path)
    config = snapshot(
        name="每日运行", backup=BackupPolicy(enabled=backup_enabled, collection_retention_days=1,
                                           analysis_retention_days=1, final_retention_days=1),
    )
    try:
        await workflow.trigger(config, session_id="named")
        config.workflow.name = "已改名"
        await workflow.wait("named")
        record = await workflow.get_session("named", version=1)
        assert record.workflow_name == "每日运行"
        assert record.status == "created"
        workflow.session_store.expire(datetime.now(UTC) + timedelta(days=2))
        assert (await workflow.get_session("named")).workflow_name == "每日运行"
    finally:
        await workflow.shutdown()
    reopened = SessionStore(path)
    try:
        assert (await SessionView(reopened).get_session("named")).workflow_name == "每日运行"
    finally:
        reopened.close()


async def test_name_is_saved_at_creation_and_independent_of_snapshot_content(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    view = SessionView(store)
    try:
        store.create("named", "demo", BackupPolicy(), workflow_name="运行名称")
        store.write(
            "named", "snapshot", stage=None, scope="parent", summary={},
            body={"snapshot": snapshot(name="快照名称").model_dump(mode="json")},
            category="snapshot",
        )
        store.write("named", "finish", stage="finish", scope="phase", summary={"status": "completed"})
        store.expire(datetime.now(UTC) + timedelta(days=2))
        assert (await view.get_session("named")).workflow_name == "运行名称"
        assert (await view.get_session("named", version=1)).workflow_name == "运行名称"
        store.create("unnamed", "demo", BackupPolicy(), workflow_name="")
        assert (await view.get_session("unnamed")).workflow_name == ""
    finally:
        store.close()


async def test_field_filters_apply_before_paging_and_compose_with_existing_constraints(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    view = SessionView(store)
    try:
        for sid, wid, name, status in [
            ("first", "daily", "Daily 日报", "completed"),
            ("second", "daily", "Daily 日报", "failed"),
            ("third", "weekly", "Weekly 周报", "completed"),
        ]:
            store.create(sid, wid, BackupPolicy(), workflow_name=name)
            store.write(sid, "finish", stage="finish", scope="phase", summary={"status": status})
        assert [r.session_id for r in await view.list_sessions(workflow_name="DAILY", limit=1)] == ["second"]
        assert [r.session_id for r in await view.list_sessions(workflow_name="日报", limit=1, offset=1)] == ["first"]
        assert [r.session_id for r in await view.list_sessions("daily", status="completed")] == ["first"]
        assert [r.session_id for r in await view.list_sessions(session_id="second")] == ["second"]
        assert await view.list_sessions(session_id="sec") == []
        assert await view.list_sessions("dai") == []
        assert await view.list_sessions(workflow_name="%") == []
        assert await view.list_sessions(workflow_name="周报", status="failed") == []
        exact = (await view.get_session("first")).created_at
        assert [r.session_id for r in await view.list_sessions(workflow_name="日报", after=exact, before=exact)] == ["first"]
        assert await view.list_sessions(workflow_name="周报", exclude_session_id="third") == []
    finally:
        store.close()
