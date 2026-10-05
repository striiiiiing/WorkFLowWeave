"""采集、AI、通知与 Workflow 持久恢复的跨模块集成测试。

装配真实注册表、资源存储、管理器、AIService、SQLite 与本地文件渠道，
只替换模型传输层；中断分析或通知后重建服务，核对原快照、输出、调用次数
及恢复结果，确保已完成步骤不重复执行、资源更新不污染旧 session。
"""

import asyncio
import time
from contextlib import asynccontextmanager

from sqlalchemy import URL, inspect
from sqlmodel import Session, create_engine, func, select

from logagent.ai import AIService
from logagent.channel import ChannelManager
from logagent.collection.manager import CollectorManager
from logagent.config import PluginRegistry, ResourceStore, expand_source
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
from logagent.workflow.execution.runner import WorkflowRunner
from logagent.workflow.storage.models import SessionHeader
from plugins.channel.file.channel import FileChannelType
from tests.fixtures.collectors import MockCollector
from tests.workflow.helpers import archived
from tests.workflow_ai_helpers import TestChannelFactory


@asynccontextmanager
async def _application(tmp_path, *, provider=None):
    registry = PluginRegistry([MockCollector()], builtin_channels=[FileChannelType()])
    report = await registry.discover_plugins(
        SystemConfig(plugin_dir=str(tmp_path / "plugins"), data_dir=str(tmp_path))
    )
    assert not report.errors
    resources = ResourceStore(tmp_path / "resources.json", collector_register=registry.collectorRegister, channel_register=registry.channelRegister)
    ai = AIService(channel_factories={"mock": provider or TestChannelFactory()})
    channels = ChannelManager(registry.channelRegister)
    service = WorkflowRunner(
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


def _save_resources(registry, resources, output_path, version):
    template = SetterTemplate(id="messages", collector="mock", setters={"fields": ["message"]})
    defaults = {"records": [{"message": version, "level": "INFO"}]}
    source = expand_source(
        SourceConfig(id="source", collector="mock", template="messages", options=defaults),
        collector=registry.collectorRegister.get("mock"),
        template=template,
    )
    assert source.template is None and source.options["mode"] == "success"
    # Mutating caller inputs cannot affect the expanded source saved below.
    defaults["records"][0]["message"] = "mutated default"
    template.setters["fields"] = []
    assert source.options["records"][0]["message"] == version
    assert source.setters == {"fields": ["message"]}
    resources.save("sources", source)
    resources.save("setters", template)
    resources.save("ai", AIConfig(id="ai", provider="mock", models={"model": {"version": version}}))
    resources.save(
        "channels", ChannelConfig(id="file", channel="file", options={"path": str(output_path)})
    )
    resources.save(
        "workflows",
        WorkflowDefinition(
            id="demo",
            name=f"Report {version}",
            sources=["source"],
            analyses=[
                AnalysisTask(id=key, ai="ai", model="model", input_prompt=f"{version}-{key}: {{input}}")
                for key in ("first", "second")
            ],
            analysis_concurrency=1,
            fan_in=FanInConfig(
                ai="ai", model="model",
                reuse_from=None,
                order=["second", "$input", "first"],
                separator="\n--\n",
                input_prompt=f"{version}-summary: {{input}}",
            ),
            channels=["file"],
        ),
    )


def _notifications(path):
    return path.read_text(encoding="utf-8")


async def test_real_modules_recovery_preserves_original_output(tmp_path):
    original_path = tmp_path / "original.jsonl"
    changed_path = tmp_path / "changed.jsonl"
    async with _application(tmp_path) as (registry, resources, service):
        _save_resources(registry, resources, original_path, "original")
        await service.validate(resources.snapshot("demo"))
        await service.trigger("demo", session_id="original-run")
        original = await service.wait("original-run")
        assert original.status == "completed"
        assert original.shared_input == '[source=source; format=none]\n{"message":"original"}'
        assert original.collection[0].items == [{"message": "original"}]
        assert "count" not in original.collection[0].model_dump()
        assert original.aggregate.text == (
            'original-summary: original-second: [source=source; format=none]\n{"message":"original"}'
            '\n--\n[source=source; format=none]\n{"message":"original"}'
            '\n--\noriginal-first: [source=source; format=none]\n{"message":"original"}'
        )
        assert original.outputs == {"final": original.aggregate.text}
        assert original.deliveries[0].status == "success"
        notifications = _notifications(original_path)
        # Full equality catches an accidental second write of the same text.
        assert notifications.endswith(f"title=Report original\n{original.outputs['final']}\n")

        history = await service.history("original-run")
        completed = {row["stage"]: row["body"] for row in history if row["scope"] == "phase"}
        assert list(completed) == ["collect", "analyze", "aggregate", "notify", "finish"]
        for body in completed.values():
            assert not {"collection", "analyses", "outputs", "deliveries"} & body.keys()
        record = await service.get_session("original-run")
        completed = {
            stage: (await service.session_view.get_phase_content(
                "original-run", stage, version=record.version
            )).content
            for stage in completed
        }
        assert completed["collect"]["collection"][0]["items"] == [{"message": "original"}]
        assert completed["analyze"]["analyses"][0]["text"] == original.analyses[0].text
        assert completed["aggregate"]["outputs"] == original.outputs
        assert completed["notify"]["deliveries"][0]["status"] == "success"

        _save_resources(registry, resources, changed_path, "changed")

    # Reopen every concrete service and SQLite connection, using current resources.
    async with _application(tmp_path) as (_, resources, service):
        assert resources.get("sources", "source").options["records"][0]["message"] == "changed"
        await service.resume("original-run")
        recovered = await service.wait("original-run")
        assert recovered == original
        assert _notifications(original_path) == notifications
        assert not changed_path.exists()
        saved = await asyncio.to_thread(service.session_store.entry, "original-run", "snapshot")
        assert saved["body"]["snapshot"]["ai"]["ai"]["models"] == {"model": {"version": "original"}}
        saved_workflow = saved["body"]["snapshot"]["workflow"]
        assert saved_workflow["analyses"][0]["input_prompt"] == "original-first: {input}"
        assert saved_workflow["fan_in"]["reuse_from"] is None

        await service.trigger("demo", session_id="changed-run")
        changed = await service.wait("changed-run")
        assert changed.status == "completed"
        assert changed.shared_input == '[source=source; format=none]\n{"message":"changed"}'
        assert changed.aggregate.text.startswith("changed-summary: changed-second:")
        assert _notifications(original_path) == notifications
        changed_notes = _notifications(changed_path)
        assert changed_notes.endswith(f"title=Report changed\n{changed.outputs['final']}\n")

    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "sessions.sqlite3")))
    try:
        tables = set(inspect(engine).get_table_names())
        assert {"session_headers", "session_entries", "checkpoints"} <= tables
        assert not {"run_sessions", "run_items", "run_stages"} & tables
        with Session(engine) as db:
            assert db.exec(select(func.count()).select_from(SessionHeader)).one() == 2
    finally:
        engine.dispose()


async def test_real_ai_cancellation_resumes_saved_snapshot_after_resource_changes(tmp_path):
    second_started = asyncio.Event()

    async def pause_second(*, config, model, system, user, credential):
        if user.startswith("original-second:"):
            second_started.set()
            await asyncio.Future()
        return {"text": user}

    original_path = tmp_path / "original.jsonl"
    changed_path = tmp_path / "changed.jsonl"
    async with _application(tmp_path, provider=TestChannelFactory(pause_second)) as (
        registry,
        resources,
        service,
    ):
        _save_resources(registry, resources, original_path, "original")
        await service.trigger("demo", session_id="interrupted")
        await asyncio.wait_for(second_started.wait(), 5)
        deadline = time.monotonic() + 5
        first_entry = None
        while first_entry is None and time.monotonic() < deadline:
            first_entry = await asyncio.to_thread(
                archived, service.session_store, "interrupted", "analyze:item:first"
            )
            if first_entry is None:
                await asyncio.sleep(0)
        assert first_entry is not None
        first = first_entry["body"]
        assert first["status"] == "success"
        assert await service.cancel("interrupted")
        assert (await asyncio.wait_for(service.wait("interrupted"), 5)).status == "cancelled"
        assert not original_path.exists()
        _save_resources(registry, resources, changed_path, "changed")

    async with _application(tmp_path) as (_, _, service):
        await service.resume("interrupted")
        recovered = await service.wait("interrupted")
        assert recovered.status == "completed"
        assert recovered.shared_input == '[source=source; format=none]\n{"message":"original"}'
        assert recovered.analyses[0].model_dump(mode="json") == first
        assert recovered.analyses[1].text == 'original-second: [source=source; format=none]\n{"message":"original"}'
        assert recovered.aggregate.text.startswith("original-summary:")
        notes = _notifications(original_path)
        assert notes.endswith(f"title=Report original\n{recovered.outputs['final']}\n")
        assert not changed_path.exists()
        history = await service.history("interrupted")
        assert sum(row["write_key"].startswith("collect:item:source:epoch:") for row in history) == 1
        assert sum(row["write_key"].startswith("analyze:item:first:epoch:") for row in history) == 1
        await service.resume("interrupted")
        assert await service.wait("interrupted") == recovered
        assert _notifications(original_path) == notes
