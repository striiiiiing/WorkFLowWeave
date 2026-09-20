"""历史采集器与只读 SessionView 的集成测试。

真实临时 SessionStore 保存业务正文，再按固定版本、最近次数、时间范围和
预算读取，断言排除当前 session、保留整组边界且不重新采集原来源。
覆盖空、缺失、过期、损坏和读取取消，确保各状态与错误原因可区分。
"""

from datetime import UTC, datetime, timedelta

import orjson
import pytest
from sqlmodel import select

from logagent.collection import CollectorManager, HistoryCollector, builtin_collectors
from logagent.config import PluginRegistry, ResourceStore
from logagent.errors import LogAgentError
from logagent.models import BackupPolicy, CollectionContext, SourceConfig, SystemConfig
from logagent.workflow import SessionStore, SessionView
from logagent.workflow.session_models import SessionEntry


@pytest.fixture
def store(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    yield store
    store.close()


def save(store, sid="old", workflow="w", text="已保存正文", enabled=True):
    store.create(sid, workflow, BackupPolicy(enabled=enabled, retention_days=1))
    store.write(sid, "collect", stage="collect", scope="phase", summary={"status": "running"},
                body={"text": text} if enabled else None,
                availability="available" if enabled else "not_saved", category="collection")
    store.write(sid, "finish", stage="finish", scope="parent", summary={"status": "completed"})


def context(store, sid="current", reader=None):
    return CollectionContext("w", sid, session_reader=reader or SessionView(store))


async def test_real_view_registration_and_content_agree_without_recollection(store, tmp_path):
    save(store)
    registry = PluginRegistry(builtin_collectors())
    report = await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    assert not report.errors
    assert {x.name for x in report.registered} == {"history", "logs", "mock"}
    manager = CollectorManager(registry.collectorRegister)
    resources = ResourceStore(tmp_path / "resources.json", collector_register=registry.collectorRegister)
    source = resources.save("sources", SourceConfig(id="past", collector="history"))
    result = await manager.collect(resources.resolve(source), context(store))
    record = await SessionView(store).get_session("old")
    phase = await SessionView(store).get_phase_content("old", "collect", version=record.version)
    assert result.status == "success" and result.count == 1
    assert result.items[0]["content"]["collect"] == phase.content
    assert result.items[0]["version"] == record.version
    assert orjson.loads(result.text) == result.items[0]


async def test_version_pinned_before_later_write(store):
    save(store)
    class RacingReader(SessionView):
        async def list_sessions(self, *args, **kwargs):
            rows = await super().list_sessions(*args, **kwargs)
            store.write("old", "new", stage="collect", scope="phase", summary={},
                        body={"text": "future"}, category="collection")
            return rows
    result = await HistoryCollector().collect({}, {}, context(store, reader=RacingReader(store)))
    assert result.items[0]["content"]["collect"] == {"text": "已保存正文"}
    assert result.items[0]["version"] < (await SessionView(store).get_session("old")).version


async def test_recent_counts_sessions_excludes_current_and_filters_time(store):
    save(store, "first")
    save(store, "other", workflow="other")
    save(store, "second")
    save(store, "current")
    collector = HistoryCollector()
    result = await collector.collect({"workflow_id": "w", "limit": 1}, {}, context(store))
    assert result.count == 1 and result.items[0]["session_id"] == "second"
    record = await SessionView(store).get_session("second")
    exact = record.created_at.isoformat()
    result = await collector.collect({"after": exact, "before": exact}, {}, context(store))
    assert result.count == 1 and result.items[0]["session_id"] == "second"
    for options in ({"session_id": "current"}, {"session_id": "absent"},
                    {"session_id": "other", "workflow_id": "w"},
                    {"after": (datetime.now(UTC) + timedelta(days=1)).isoformat()}):
        assert (await collector.collect(options, {}, context(store))).status == "empty"


async def test_empty_missing_expired_corrupt_are_distinct(store):
    collector = HistoryCollector()
    assert (await collector.collect({}, {}, context(store))).status == "empty"
    save(store, enabled=False)
    result = await collector.collect({}, {}, context(store))
    assert result.status == "missing" and result.error.details["availability"] == "not_saved"
    save(store, "expiring")
    store.expire(datetime.now(UTC) + timedelta(days=2))
    result = await collector.collect({"session_id": "expiring"}, {}, context(store))
    assert result.status == "missing" and result.error.details["availability"] == "expired"
    save(store, "broken")
    with store._transaction() as session:
        row = session.exec(select(SessionEntry).where(
            SessionEntry.session_id == "broken", SessionEntry.write_key == "collect",
        )).one()
        row.body = '{"text":"private-corrupt"}'
        session.add(row)
    result = await collector.collect({"session_id": "broken"}, {}, context(store))
    assert result.status == "failed" and "private-corrupt" not in result.model_dump_json()
    missing = await collector.collect({}, {}, CollectionContext("w", "current"))
    assert missing.status == "missing"


async def test_budget_includes_rendered_fields_groups_and_preserves_whole_sessions(store):
    save(store, "one", text="旧" * 200)
    save(store, "two", text="新" * 200)
    collector = HistoryCollector()
    ctx = context(store)
    single = await collector.collect({"limit": 1}, {}, ctx)
    size = len(single.text.encode())
    exact = await collector.collect({"limit": 1, "max_tokens": size}, {}, ctx)
    assert exact.status == "success" and exact.metadata["estimated_tokens"] == size
    failed = await collector.collect({"limit": 1, "max_tokens": size - 1}, {}, ctx)
    assert failed.status == "failed"
    result = await collector.collect({"max_tokens": size, "overflow": "truncate"}, {}, ctx)
    assert result.count == 1 and result.items == single.items
    assert result.metadata["truncated"] and result.metadata["omitted"][0]["session_id"] == "one"
    grouped = await collector.collect({}, {"group_by": "workflow_id"}, ctx)
    assert grouped.count == 2 and len(orjson.loads(grouped.text)["items"]) == 2
    assert (await collector.collect({}, {"fields": []}, ctx)).status == "filtered_empty"


@pytest.mark.parametrize("options,setters", [
    ({"limit": 0}, {}), ({"limit": 1001}, {}), ({"limit": 1.0}, {}),
    ({"max_tokens": True}, {}), ({"stages": []}, {}), ({"unexpected": True}, {}),
    ({"after": "2026-01-01T00:00:00"}, {}),
    ({"after": "2026-02-01T00:00:00Z", "before": "2026-01-01T00:00:00Z"}, {}),
    ({}, {"fields": ["status"], "group_by": "workflow_id"}),
])
def test_pure_validation(options, setters):
    with pytest.raises(LogAgentError):
        HistoryCollector().validate(options, setters)


async def test_selected_version_disappearance_is_missing_and_cancellation_propagates(store):
    import asyncio

    save(store)
    class MissingReader(SessionView):
        async def get_phase_content(self, *args, **kwargs):
            raise LogAgentError("version_not_found", "private")
    result = await HistoryCollector().collect({}, {}, context(store, reader=MissingReader(store)))
    assert result.status == "missing" and "private" not in result.model_dump_json()

    entered = asyncio.Event()
    class BlockingReader(SessionView):
        async def get_phase_content(self, *args, **kwargs):
            entered.set()
            await asyncio.Future()
    task = asyncio.create_task(HistoryCollector().collect({}, {}, context(store, reader=BlockingReader(store))))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
