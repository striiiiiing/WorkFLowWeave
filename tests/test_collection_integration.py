import asyncio
import json

import pytest
from test_archive import NOW, write_session

from logagent.archive import FileArchiveReader
from logagent.collection import CollectorManager
from logagent.config import PluginRegistry, expand_source
from logagent.errors import LogAgentError
from logagent.models import CollectionContext, SourceConfig, SystemConfig


def effective(registry, source):
    return expand_source(
        source,
        collector=registry.collectorRegister.get(source.collector),
        options_defaults=registry.collectorRegister.options_defaults(source.collector),
    )


async def test_builtin_registry_manager_and_real_archive_and_logs_work_together(tmp_path):
    data_dir = tmp_path / "data"
    write_session(data_dir, "prior", workflow_id="past")
    before = {path.relative_to(data_dir): path.read_bytes() for path in data_dir.rglob("*.json")}
    log_file = tmp_path / "application.jsonl"
    events = [
        {"time": NOW.isoformat(), "level": "INFO", "module": "collection", "message": message}
        for message in ("first event", "second event")
    ]
    log_file.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    registry = PluginRegistry()
    report = await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    assert [description.name for description in report.registered] == ["mock", "logs", "history"]
    assert report.errors == []
    manager = CollectorManager(registry.collectorRegister)
    sources = [
        SourceConfig(id="mock_input", collector="mock"),
        SourceConfig(id="logs_input", collector="logs", setters={"group_by": "module"}),
        SourceConfig(id="history_input", collector="history", options={"workflow_id": "past"}),
    ]
    sources = [effective(registry, source) for source in sources]
    for source in sources:
        manager.validate(source)
    context = CollectionContext(
        workflow_id="current",
        session_id="current_run",
        archive=FileArchiveReader(data_dir, clock=lambda: NOW),
        log_path=str(log_file),
    )
    mock, logs, history = await asyncio.gather(
        *(manager.collect(source, context) for source in sources)
    )
    assert [mock.status, logs.status, history.status] == ["success"] * 3
    assert mock.count == 1 and logs.count == 2 and history.count == 1
    assert len(logs.items) == 1  # Group count is not the event count.
    assert history.items[0]["session_id"] == "prior"
    assert "final body" in history.text
    assert history.metadata["used_bytes"] == len(history.text.encode("utf-8"))
    assert history.metadata["budget_algorithm"] == "utf8_bytes_v1"
    assert {
        path.relative_to(data_dir): path.read_bytes() for path in data_dir.rglob("*.json")
    } == before


async def test_plugin_with_multiple_collectors_and_failed_peer_is_consumed_only_through_registry(
    tmp_path,
):
    root = tmp_path / "plugins"
    for plugin_id, body in {
        "a_good": """
from logagent.collection.mock import MockCollector
class First(MockCollector):
    name = "external_first"
class Second(MockCollector):
    name = "external_second"
class Plugin:
    def register(self, api):
        api.register_collector(First())
        api.register_collector(Second())
plugin = Plugin()
""",
        "b_broken": """
from logagent.collection.mock import MockCollector
class Temporary(MockCollector):
    name = "temporary"
class Plugin:
    def register(self, api):
        api.register_collector(Temporary())
        api.register_collector(MockCollector())
plugin = Plugin()
""",
    }.items():
        directory = root / plugin_id
        directory.mkdir(parents=True)
        (directory / "plugin.json").write_text(
            json.dumps(
                {
                    "id": plugin_id,
                    "version": "1",
                    "kind": "collector",
                    "api_version": 1,
                    "entry": {"backend": "main.py"},
                }
            )
        )
        (directory / "main.py").write_text(body)
    registry = PluginRegistry()
    report = await registry.discover_plugins(SystemConfig(plugin_dir=str(root)))
    assert len(report.errors) == 1
    manager = CollectorManager(registry.collectorRegister)
    context = CollectionContext(workflow_id="current", session_id="run")
    results = await asyncio.gather(
        *(
            manager.collect(SourceConfig(id=f"source_{name}", collector=name), context)
            for name in ("external_first", "external_second", "temporary", "mock")
        )
    )
    assert [result.status for result in results] == ["success", "success", "missing", "success"]
    assert results[2].error.details["discovery_errors"][0]["details"]["plugin"] == "b_broken"


async def test_corrupt_archive_is_failed_without_partial_history_or_private_body(tmp_path):
    write_session(tmp_path, "prior", workflow_id="past")
    (tmp_path / "sessions" / "prior" / "final.json").write_text("secret damaged content")
    registry = PluginRegistry()
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    result = await CollectorManager(registry.collectorRegister).collect(
        SourceConfig(id="history", collector="history", options={"workflow_id": "past"}),
        CollectionContext(
            workflow_id="current", session_id="run", archive=FileArchiveReader(tmp_path)
        ),
    )
    assert result.status == "failed" and result.error.details["reason"] == "corrupt"
    assert result.items == [] and result.count == 0 and result.text == ""
    assert "secret damaged content" not in result.model_dump_json()


@pytest.mark.parametrize("collector", ["logs", "history"])
async def test_cross_field_validation_is_exposed_through_the_manager(tmp_path, collector):
    registry = PluginRegistry()
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    times = {"start_time": "2026-09-14T00:00:00Z", "end_time": "2026-09-13T00:00:00Z"}
    source = SourceConfig(
        id="one",
        collector=collector,
        options={"workflow_id": "past", **times} if collector == "history" else {},
        setters=times if collector == "logs" else {},
    )
    manager = CollectorManager(registry.collectorRegister)
    with pytest.raises(LogAgentError) as caught:
        manager.validate(source)
    assert caught.value.code == "invalid_config"
    result = await manager.collect(
        source, CollectionContext(workflow_id="current", session_id="run")
    )
    assert result.status == "failed"  # Validation occurs before missing file/archive checks.
