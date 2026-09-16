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
    service = WorkflowService(
        CollectorManager(registry.collectorRegister),
        ai,
        channels,
        resources,
        database=tmp_path / "sessions.sqlite3",
    )
    try:
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


async def test_real_modules_recovery_preserves_original_output(tmp_path):
    original_path = tmp_path / "original.jsonl"
    changed_path = tmp_path / "changed.jsonl"
    async with _application(tmp_path) as (registry, resources, service):
        _save_resources(registry, resources, original_path, "original")
        await service.validate(resources.snapshot("demo"))
        await service.trigger("demo", session_id="original-run")
        original = await service.wait("original-run")
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

        history = await service.history("original-run")
        completed = {row["stage"]: row["body"] for row in history if row["scope"] == "phase"}
        assert list(completed) == ["collect", "analyze", "aggregate", "notify", "finish"]
        assert completed["collect"]["collection"][0]["items"] == [{"message": "original"}]
        assert completed["analyze"]["analyses"][0]["text"] == original.analyses[0].text
        assert completed["aggregate"]["outputs"] == original.outputs
        assert completed["notify"]["deliveries"][0]["status"] == "success"

        _save_resources(registry, resources, changed_path, "changed")

    # Reopen every concrete service and SQLite connection, using current resources.
    async with _application(tmp_path) as (_, resources, service):
        assert resources.get("sources", "source").options["records"][0]["message"] == "changed"
        await service.recover("original-run")
        recovered = await service.wait("original-run")
        assert recovered == original
        assert _notifications(original_path) == notifications
        assert not changed_path.exists()
        saved = await asyncio.to_thread(service.session_store.entry, "original-run", "snapshot")
        assert saved["body"]["snapshot"]["ai"]["ai"]["model"] == "model-original"

        await service.trigger("demo", session_id="changed-run")
        changed = await service.wait("changed-run")
        assert changed.status == "completed"
        assert changed.shared_input == '{"message":"changed"}'
        assert changed.aggregate.text.startswith("changed-summary: changed-second:")
        assert _notifications(original_path) == notifications
        changed_notes = _notifications(changed_path)
        assert len(changed_notes) == 1 and changed_notes[0]["text"] == changed.outputs["final"]
        assert changed_notes[0]["title"] == "Report changed"
        assert changed_notes[0]["session_id"] == "changed-run"

    with sqlite3.connect(tmp_path / "sessions.sqlite3") as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"session_headers", "session_entries", "checkpoints"} <= tables
        assert not {"run_sessions", "run_items", "run_stages"} & tables
        assert db.execute("SELECT count(*) FROM session_headers").fetchone()[0] == 2


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
        await service.trigger("demo", session_id="interrupted")
        await asyncio.wait_for(second_started.wait(), 5)
        first = (
            await asyncio.to_thread(
                service.session_store.entry, "interrupted", "analyze:item:first"
            )
        )["body"]
        assert first["status"] == "success"
        assert await service.cancel("interrupted")
        assert (await asyncio.wait_for(service.wait("interrupted"), 5)).status == "cancelled"
        assert not original_path.exists()
        _save_resources(registry, resources, changed_path, "changed")

    async with _application(tmp_path) as (_, _, service):
        await service.recover("interrupted")
        recovered = await service.wait("interrupted")
        assert recovered.status == "completed"
        assert recovered.shared_input == '{"message":"original"}'
        assert recovered.analyses[0].model_dump(mode="json") == first
        assert recovered.analyses[1].text == 'original-second: {"message":"original"}'
        assert recovered.aggregate.text.startswith("original-summary:")
        notes = _notifications(original_path)
        assert len(notes) == 1 and notes[0]["text"] == recovered.outputs["final"]
        assert not changed_path.exists()
        history = await service.history("interrupted")
        assert sum(row["write_key"] == "collect:item:source" for row in history) == 1
        assert sum(row["write_key"] == "analyze:item:first" for row in history) == 1
        await service.recover("interrupted")
        assert await service.wait("interrupted") == recovered
        assert _notifications(original_path) == notes
