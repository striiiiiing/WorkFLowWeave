"""Exercise durable workflows through the real registry, managers, and local plugins."""

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager

from logagent.ai import AIService, MockProvider
from logagent.channel import ChannelManager, MockFileChannelType
from logagent.collection.manager import CollectorManager
from logagent.collection.mock import MockCollector
from logagent.config import PluginRegistry, SQLiteResourceStore, expand_source
from logagent.models import (
    AIConfig,
    AnalysisTask,
    ChannelConfig,
    FanInConfig,
    SetterTemplate,
    SourceConfig,
    SystemConfig,
    WorkflowDefinition,
)
from logagent.workflow import WorkflowService


@asynccontextmanager
async def _application(tmp_path, *, provider=None):
    registry = PluginRegistry([MockCollector()], builtin_channels=[MockFileChannelType()])
    report = await registry.discover_plugins(
        SystemConfig(plugin_dir=str(tmp_path / "plugins"), data_dir=str(tmp_path))
    )
    assert not report.errors
    resources = SQLiteResourceStore(tmp_path / "logagent.sqlite3")
    ai = AIService(providers={"mock": provider or MockProvider()})
    channels = ChannelManager(registry.channelRegister)
    service = WorkflowService(CollectorManager(registry.collectorRegister), ai, channels, resources)
    try:
        assert service.run_store.location == resources.location
        yield registry, resources, service
    finally:
        await service.shutdown()
        await ai.close()
        await channels.stop()
        resources.close()


def _save_resources(registry, resources, output_path, version):
    template = SetterTemplate(id="messages", collector="mock", setters={"fields": ["message"]})
    defaults = {"records": [{"message": version, "level": "INFO"}]}
    source = expand_source(
        SourceConfig(id="source", collector="mock", template="messages"),
        collector=registry.collectorRegister.get("mock"),
        template=template,
        options_defaults=defaults,
    )
    assert source.template is None and source.options["mode"] == "success"
    # Mutating caller inputs cannot affect the expanded source saved below.
    defaults["records"][0]["message"] = "mutated default"
    template.setters["fields"] = []
    assert source.options["records"][0]["message"] == version
    assert source.setters == {"fields": ["message"]}
    resources.save("sources", source)
    resources.save("setters", template)
    resources.save("ai", AIConfig(id="ai", provider="mock", model=f"model-{version}"))
    resources.save(
        "channels", ChannelConfig(id="file", channel="mock", options={"path": str(output_path)})
    )
    resources.save(
        "workflows",
        WorkflowDefinition(
            id="demo",
            name=f"Report {version}",
            sources=["source"],
            analyses=[
                AnalysisTask(id=key, ai="ai", prompt=f"{version}-{key}: {{input}}")
                for key in ("first", "second")
            ],
            analysis_concurrency=1,
            fan_in=FanInConfig(
                ai="ai",
                order=["second", "$input", "first"],
                separator="\n--\n",
                prompt=f"{version}-summary: {{input}}",
            ),
            channels=["file"],
        ),
    )


def _notifications(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


async def test_real_modules_share_sqlite_and_recovery_preserves_original_output(tmp_path):
    original_path = tmp_path / "original.jsonl"
    changed_path = tmp_path / "changed.jsonl"
    async with _application(tmp_path) as (registry, resources, service):
        _save_resources(registry, resources, original_path, "original")
        await service.validate(resources.snapshot("demo"))
        original = await service.trigger("demo", session_id="original-run")
        assert original.status == "completed"
        assert original.shared_input == '{"message":"original"}'
        assert original.collection[0].items == [{"message": "original"}]
        assert original.collection[0].count == 1
        assert original.aggregate.text == (
            'original-summary: original-second: {"message":"original"}'
            '\n--\n{"message":"original"}'
            '\n--\noriginal-first: {"message":"original"}'
        )
        assert original.outputs == {"final": original.aggregate.text}
        assert original.deliveries[0].status == "success"
        notifications = _notifications(original_path)
        assert len(notifications) == 1
        assert notifications[0]["text"] == original.outputs["final"]
        assert notifications[0]["session_id"] == "original-run"

        history = await service.history("original-run", limit=1000)
        completed = {
            row["stage"]: row["payload"]
            for row in history
            if row["event"] == "completed" and "session_id" in row["payload"]
        }
        assert list(completed) == ["collect", "analyze", "aggregate", "notify", "finish"]
        assert completed["collect"]["collection"][0]["items"] == [{"message": "original"}]
        assert completed["analyze"]["analyses"][0]["text"] == original.analyses[0].text
        assert completed["aggregate"]["outputs"] == original.outputs
        assert completed["notify"]["deliveries"][0]["status"] == "success"

        _save_resources(registry, resources, changed_path, "changed")

    # Reopen every concrete service and SQLite connection, using current resources.
    async with _application(tmp_path) as (_, resources, service):
        assert resources.get("sources", "source").options["records"][0]["message"] == "changed"
        recovered = await service.recover("original-run")
        assert recovered == original
        assert _notifications(original_path) == notifications
        assert not changed_path.exists()
        saved = await service.get_session("original-run")
        assert saved["snapshot"]["sources"]["source"]["options"]["records"][0] == {
            "message": "original",
            "level": "INFO",
        }
        assert saved["snapshot"]["ai"]["ai"]["model"] == "model-original"

        changed = await service.trigger("demo", session_id="changed-run")
        assert changed.status == "completed"
        assert changed.shared_input == '{"message":"changed"}'
        assert changed.aggregate.text.startswith("changed-summary: changed-second:")
        assert _notifications(original_path) == notifications
        changed_notes = _notifications(changed_path)
        assert len(changed_notes) == 1 and changed_notes[0]["text"] == changed.outputs["final"]
        assert changed_notes[0]["title"] == "Report changed"
        assert changed_notes[0]["session_id"] == "changed-run"

    with sqlite3.connect(tmp_path / "logagent.sqlite3") as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"resources", "run_sessions", "run_stages", "run_history", "checkpoints"} <= tables
        assert db.execute("SELECT count(*) FROM run_sessions").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM resources").fetchone()[0] == 5


async def test_real_ai_cancellation_resumes_saved_snapshot_after_resource_changes(tmp_path):
    second_started = asyncio.Event()

    async def pause_second(*, config, system, user, credential):
        if user.startswith("original-second:"):
            second_started.set()
            await asyncio.Future()
        return {"text": user}

    original_path = tmp_path / "original.jsonl"
    changed_path = tmp_path / "changed.jsonl"
    async with _application(tmp_path, provider=MockProvider(pause_second)) as (
        registry,
        resources,
        service,
    ):
        _save_resources(registry, resources, original_path, "original")
        running = asyncio.create_task(service.trigger("demo", session_id="interrupted"))
        await asyncio.wait_for(second_started.wait(), 5)
        first = service.run_store.item_results("interrupted", "analyze")["first"]
        assert first["status"] == "success"
        assert await service.cancel("interrupted")
        assert (await asyncio.wait_for(running, 5)).status == "cancelled"
        assert not original_path.exists()
        _save_resources(registry, resources, changed_path, "changed")

    async with _application(tmp_path) as (_, _, service):
        recovered = await service.recover("interrupted")
        assert recovered.status == "completed"
        assert recovered.shared_input == '{"message":"original"}'
        assert recovered.analyses[0].model_dump(mode="json") == first
        assert recovered.analyses[1].text == 'original-second: {"message":"original"}'
        assert recovered.aggregate.text.startswith("original-summary:")
        notes = _notifications(original_path)
        assert len(notes) == 1 and notes[0]["text"] == recovered.outputs["final"]
        assert not changed_path.exists()
        history = await service.history("interrupted", limit=1000)
        assert (
            sum(row["stage"] == "collect" and row["event"] == "item_started" for row in history)
            == 1
        )
        assert (
            sum(
                row["stage"] == "analyze"
                and row["event"] == "item_started"
                and row["payload"]["task_id"] == "first"
                for row in history
            )
            == 1
        )
        assert await service.recover("interrupted") == recovered
        assert _notifications(original_path) == notes
