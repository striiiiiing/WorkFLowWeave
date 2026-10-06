"""应用生命周期装配与资源所有权测试。

通过临时配置、真实插件/存储及可控模型替身启动 ApplicationLifecycle，验证
启动失败清理、资源和插件 reload、定时与手动触发共享容量及快照、健康恢复。
用事件屏障和故障注入重现启动/关闭/热更新竞争，断言准入及逆序释放边界，
并检查 JSON 日志轮转脱敏及日志采集；所有持久化限定在临时目录。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import URL
from sqlmodel import Session, create_engine, func, select

from logagent.channel import builtin_channels
from logagent.config import PluginRegistry, ResourceStore
from logagent.errors import LogAgentError
from logagent.lifecycle import ApplicationLifecycle, JsonLogSink
from logagent.models import (
    AIConfig,
    AnalysisTask,
    ChannelConfig,
    SourceConfig,
    SystemConfig,
    WorkflowDefinition,
)
from logagent.workflow.storage.models import SessionEntry, SessionHeader
from tests.fixtures.plugin_helpers import install_channel_plugin
from tests.workflow_ai_helpers import TestChannelFactory

_COLLECTOR_PLUGIN = """
from logagent.models import CollectorOutput

class ExternalCollector:
    name = "external"
    description = "External lifecycle test collector"
    fields = []
    count_unit = "records"
    options_schema = {"type": "object", "additionalProperties": False}
    setters_schema = {"type": "object", "additionalProperties": False}

    async def collect(self, options, setters, context):
        return CollectorOutput(status="success", text="external-data", count=1)

class Plugin:
    def register(self, api):
        api.register_collector(ExternalCollector())

plugin = Plugin()
"""


def _channel_plugin(prefix: str) -> str:
    return f"""
import asyncio
from pathlib import Path

class ExternalChannel:
    def __init__(self, config):
        self.path = Path(config.options["path"])

    async def _record(self, value):
        def write():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(value + "\\n")

        await asyncio.to_thread(write)

    async def start(self):
        await self._record("{prefix}-start")

    async def send(self, notification, *, options):
        await self._record("{prefix}-send")

    async def stop(self):
        await self._record("{prefix}-stop")

class ExternalChannelType:
    name = "external_channel"
    description = "External lifecycle test channel"
    capabilities = ["notification"]
    options_schema = {{
        "type": "object",
        "properties": {{
            "path": {{
                "type": "string",
                "minLength": 1,
                "description": "Channel event output path",
            }}
        }},
        "required": ["path"],
        "additionalProperties": False,
    }}

    async def create(self, config, credentials):
        return ExternalChannel(config)

class Plugin:
    def register(self, api):
        api.register_channel(ExternalChannelType())

plugin = Plugin()
"""


class BlockingChannelFactory(TestChannelFactory):
    def __init__(self) -> None:
        super().__init__(self.respond)
        self.calls = 0
        self.inputs: list[str] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.updated = asyncio.Event()

    async def respond(self, config, *, model, system, user, credential=None):
        self.calls += 1
        self.inputs.append(user)
        self.started.set()
        self.updated.set()
        await self.release.wait()
        return {"text": user}

    async def close(self) -> None:
        pass


def _config(tmp_path: Path, **kwargs) -> SystemConfig:
    return SystemConfig(
        data_dir=str(tmp_path / "data"),
        plugin_dir=str(tmp_path / "plugins"),
        log_file=str(tmp_path / "logs" / "app.jsonl"),
        **kwargs,
    )


def _write_plugin(
    root: Path,
    plugin_id: str,
    body: str,
    *,
    kind: str = "collector",
) -> Path:
    root = Path(root)
    package = root / plugin_id
    package.mkdir(parents=True, exist_ok=True)
    (package / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "version": "1.0",
                "kind": kind,
                "api_version": 1,
                "entry": {"backend": "main.py"},
            }
        ),
        encoding="utf-8",
    )
    path = package / "main.py"
    path.write_text(body, encoding="utf-8")
    return path


async def _seed_resources(
    config: SystemConfig,
    *,
    collector: str = "mock",
    channel: str | None = None,
    channel_path: Path | None = None,
    interval: float = 10.0,
    enabled: bool = True,
) -> None:
    if channel == "file":
        install_channel_plugin("file", config.plugin_dir)
    registry = PluginRegistry(
        [],
        builtin_channels=builtin_channels(),
    )
    await registry.discover_plugins(config)
    store = ResourceStore(
        Path(config.data_dir) / "resources.json",
        collector_register=registry.collectorRegister,
        channel_register=registry.channelRegister,
        data_dir=config.data_dir,
    )
    store.save("sources", SourceConfig(id="source", call={
        "kind": "cli", "mode": "argv", "executable": "printf",
        "argv": ["%s", "external-data" if collector == "external" else "LogAgent mock record"],
    }))
    if channel is not None:
        store.save(
            "channels",
            ChannelConfig(
                id="channel",
                channel=channel,
                options={"path": str(channel_path or (Path(config.data_dir) / "channel.txt"))},
            ),
        )
    store.save("ai", AIConfig(id="ai", provider="mock", models={"model": {}}))
    store.save(
        "workflows",
        WorkflowDefinition(
            id="timed",
            sources=["source"],
            analyses=[AnalysisTask(user_prompt="analyze input", id="task", ai="ai", model="model")],
            channels=["channel"] if channel else [],
            schedule={"type": "every", "every_seconds": interval} if interval else None,
            enabled=enabled,
        ),
    )


def _rewrite_workflow(config: SystemConfig, **updates) -> None:
    path = Path(config.data_dir) / "resources.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["workflows"]["timed"].update(updates)
    path.write_text(json.dumps(data), encoding="utf-8")


async def _wait_for_calls(provider: BlockingChannelFactory, count: int) -> None:
    async with asyncio.timeout(5):
        while provider.calls < count:
            provider.updated.clear()
            if provider.calls >= count:
                break
            await provider.updated.wait()


def _has_lifecycle_handler() -> bool:
    return any(
        getattr(handler, "_logagent_lifecycle_handler", False)
        for handler in logging.getLogger("logagent").handlers
    )


async def test_start_failure_retains_diagnostic_and_cleans_owned_resources(tmp_path):
    class BrokenSaver:
        async def setup(self):
            raise RuntimeError("checkpoint setup failed")

    class CheckpointerContext:
        def __init__(self):
            self.entered = False
            self.exited = False

        async def __aenter__(self):
            self.entered = True
            return BrokenSaver()

        async def __aexit__(self, exc_type, exc, traceback):
            self.exited = True

    context = CheckpointerContext()
    lifecycle = ApplicationLifecycle(
        _config(tmp_path),
        channel_factories={"mock": TestChannelFactory()},
        checkpointer_context_factory=lambda _: context,
    )

    with pytest.raises(LogAgentError) as caught:
        await lifecycle.start()

    assert caught.value.code == "lifecycle_start_failed"
    assert lifecycle.failure.details["stage"] == "checkpointer"
    assert context.entered and context.exited
    assert lifecycle._services is None
    assert lifecycle._session_store is None
    assert lifecycle._log_sink is None
    assert not _has_lifecycle_handler()

    health = await lifecycle.health()
    assert health.status == "unavailable"
    assert health.accepting_runs is False
    with pytest.raises(LogAgentError, match="应用启动失败"):
        await lifecycle.start()


async def test_temporary_config_full_assembly_health_and_idempotent_shutdown(tmp_path):
    config_dir = tmp_path / "configuration"
    config_dir.mkdir()
    system_file = config_dir / "system.json"
    system_file.write_text(
        json.dumps(
            {
                "data_dir": "data",
                "plugin_dir": "plugins",
                "log_file": "logs/app.jsonl",
                "max_concurrent_runs": 2,
            }
        ),
        encoding="utf-8",
    )
    lifecycle = await ApplicationLifecycle.from_file(
        system_file,
        channel_factories={"mock": TestChannelFactory()},
    )

    services = await lifecycle.start()
    assert services.collectors.describe() == []
    assert {item.name for item in services.channels.describe()} == {"web"}
    assert services.channels._entries == {}
    health = await lifecycle.health()
    assert health.status == "ready"
    assert health.accepting_runs is True

    started = time.monotonic()
    await asyncio.gather(*(lifecycle.shutdown() for _ in range(3)))
    assert time.monotonic() - started < 60
    assert (await lifecycle.health()).status == "unavailable"
    assert (await lifecycle.health()).accepting_runs is False
    with pytest.raises(LogAgentError) as caught:
        await lifecycle.start()
    assert caught.value.code == "shutdown"

    content = await asyncio.to_thread(Path(services.log_path).read_text, encoding="utf-8")
    events = [json.loads(line) for line in content.splitlines()]
    assert {event["event"] for event in events} >= {
        "application_started",
        "application_stopped",
    }


async def test_resources_reload_rebuilds_future_plan_and_disabled_rejects_manual(tmp_path):
    config = _config(tmp_path)
    await _seed_resources(config)
    lifecycle = ApplicationLifecycle(
        config,
        channel_factories={"mock": TestChannelFactory()},
    )
    services = await lifecycle.start()
    assert services.intervals.scheduler.get_job("timed").trigger.interval.total_seconds() == 10

    _rewrite_workflow(config, schedule={"type": "every", "every_seconds": 25})
    await lifecycle.reload("resources")
    assert services.intervals.scheduler.get_job("timed").trigger.interval.total_seconds() == 25

    _rewrite_workflow(config, enabled=False)
    await lifecycle.reload("resources")
    assert "timed" not in services.intervals._plans
    with pytest.raises(LogAgentError) as caught:
        await services.workflow.trigger("timed", session_id="disabled")
    assert caught.value.code == "workflow_disabled"

    await lifecycle.shutdown()


async def test_interval_and_manual_share_capacity_snapshot_and_cancel(tmp_path):
    config = _config(tmp_path, max_concurrent_runs=1)
    await _seed_resources(config)
    provider = BlockingChannelFactory()
    lifecycle = ApplicationLifecycle(
        config,
        channel_factories={"mock": provider},
    )
    services = await lifecycle.start()

    await services.workflow.trigger("timed", session_id="manual")
    await asyncio.wait_for(provider.started.wait(), 5)
    assert await services.intervals._execute("timed", services.intervals._plans["timed"]) is None
    assert provider.calls == 1
    assert "LogAgent mock record" in provider.inputs[0]

    await services.workflow.cancel("manual")
    assert (await services.workflow.wait("manual")).status == "cancelled"

    services.resources.save(
        "sources",
        SourceConfig(
            id="source",
            call={"kind": "cli", "mode": "argv", "executable": "printf",
                  "argv": ["%s", "new snapshot"]},
        ),
    )
    scheduled = await services.intervals._execute("timed", services.intervals._plans["timed"])
    assert scheduled is not None
    await _wait_for_calls(provider, 2)
    assert "new snapshot" in provider.inputs[1]

    await services.workflow.cancel(scheduled)
    assert (await services.workflow.wait(scheduled)).status == "cancelled"
    await lifecycle.shutdown()


async def test_shutdown_waits_for_admitted_interval_archive_before_stopping(tmp_path):
    config = _config(tmp_path, max_concurrent_runs=1)
    notifications = tmp_path / "notifications.txt"
    await _seed_resources(
        config,
        channel="file",
        channel_path=notifications,
        interval=0.05,
    )
    lifecycle = ApplicationLifecycle(
        config,
        channel_factories={"mock": TestChannelFactory()},
        shutdown_timeout=5.0,
    )
    services = await lifecycle.start()

    loop = asyncio.get_running_loop()
    snapshot_written = asyncio.Event()
    release_snapshot = threading.Event()
    session_ids: list[str] = []
    original_write = services.session_store.write

    def blocking_snapshot_write(session_id, key, **kwargs):
        entry = original_write(session_id, key, **kwargs)
        if key == "snapshot":
            session_ids.append(session_id)
            loop.call_soon_threadsafe(snapshot_written.set)
            release_snapshot.wait()
        return entry

    services.session_store.write = blocking_snapshot_write
    shutdown_task: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(snapshot_written.wait(), 5)
        assert len(session_ids) == 1
        # The event consumer archives the snapshot inside the admitted run;
        # shutdown must wait for that active task to finish the blocked write.
        assert services.workflow.coordinator.active == 1
        assert (
            await asyncio.to_thread(
                services.session_store.entry,
                session_ids[0],
                "created",
            )
            is not None
        )

        shutdown_task = asyncio.create_task(lifecycle.shutdown())
        await asyncio.sleep(0.05)
        assert not shutdown_task.done()

        release_snapshot.set()
        await asyncio.wait_for(shutdown_task, 10)
    finally:
        release_snapshot.set()
        if not lifecycle._shutdown_complete:
            await lifecycle.shutdown()

    assert not services.intervals.scheduler.running
    assert services.workflow.coordinator.active == 0
    assert not notifications.exists()

    database = Path(config.data_dir) / "workflows.sqlite3"
    engine = create_engine(URL.create("sqlite", database=str(database)))
    try:
        with Session(engine) as connection:
            session_count = connection.exec(select(func.count()).select_from(SessionHeader)).one()
            summaries = connection.exec(select(SessionEntry.summary).where(
                SessionEntry.scope == "parent",
            ).order_by(SessionEntry.version)).all()
            parent_states = [value["status"] for summary in summaries
                             if "status" in (value := json.loads(summary))]
    finally:
        engine.dispose()
    assert session_count == 1
    assert parent_states[-1] == "cancelled"


async def test_plugin_reload_conflict_restores_admission_and_later_success_recovers(tmp_path):
    config = _config(tmp_path, max_concurrent_runs=1)
    _write_plugin(config.plugin_dir, "external", _COLLECTOR_PLUGIN)
    await _seed_resources(config, collector="external")
    provider = BlockingChannelFactory()
    lifecycle = ApplicationLifecycle(config, channel_factories={"mock": provider})
    services = await lifecycle.start()

    await services.workflow.trigger("timed", session_id="active")
    await asyncio.wait_for(provider.started.wait(), 5)
    with pytest.raises(LogAgentError) as caught:
        await lifecycle.reload("plugins")
    assert caught.value.code == "plugin_reload_conflict"
    assert services.workflow.coordinator.accepting is True
    assert services.intervals.paused is False
    assert "external" in {item.name for item in services.plugins.collectorRegister.describe()}
    assert (await lifecycle.health()).status == "degraded"

    await services.workflow.cancel("active")
    assert (await services.workflow.wait("active")).status == "cancelled"
    report = await lifecycle.reload("plugins")
    assert report.errors == []
    assert (await lifecycle.health()).status == "ready"
    await lifecycle.shutdown()


async def test_plugin_reload_conflict_includes_active_agent_turn(tmp_path):
    lifecycle = ApplicationLifecycle(_config(tmp_path), channel_factories={"mock": TestChannelFactory()})
    services = await lifecycle.start()
    release = asyncio.Event()
    active = asyncio.create_task(release.wait())
    from logagent.agent.runtime.turns import ActiveTurn
    services.agent.turns._turns["agent-active"] = ActiveTurn("synthetic", "agent-active", active)
    generation = services.plugins.generation
    try:
        with pytest.raises(LogAgentError) as caught:
            await lifecycle.reload("plugins")
        assert caught.value.code == "plugin_reload_conflict"
        assert caught.value.details["active_agent_runs"] == 1
        assert services.plugins.generation == generation
        assert services.agent.accepting is True
    finally:
        release.set()
        active.cancel()
        await asyncio.gather(active, return_exceptions=True)
        services.agent.turns._turns.pop("agent-active", None)
        await lifecycle.shutdown()


async def test_invalid_plugin_degrades_and_fixed_reload_recovers_saved_resource(tmp_path):
    config = _config(tmp_path)
    entry = _write_plugin(config.plugin_dir, "external", _COLLECTOR_PLUGIN)
    await _seed_resources(config, collector="external")
    entry.write_text("raise RuntimeError('broken plugin')\n", encoding="utf-8")

    lifecycle = ApplicationLifecycle(config, channel_factories={"mock": TestChannelFactory()})
    services = await lifecycle.start()
    degraded = await lifecycle.health()
    assert degraded.status == "degraded"
    assert degraded.accepting_runs is True
    plugin_component = next(item for item in degraded.components if item.component == "plugins")
    assert plugin_component.status == "degraded"
    assert plugin_component.error is not None

    entry.write_text(_COLLECTOR_PLUGIN, encoding="utf-8")
    report = await lifecycle.reload("plugins")
    assert report.errors == []
    assert (await lifecycle.health()).status == "ready"
    await services.workflow.trigger("timed", session_id="recovered")
    result = await services.workflow.wait("recovered")
    assert result.status == "completed"
    assert "external-data" in result.shared_input
    await lifecycle.shutdown()


async def test_plugin_reload_unloads_old_owner_and_injects_new_view(tmp_path):
    config = _config(tmp_path)
    events = tmp_path / "channel-events.txt"
    entry = _write_plugin(
        config.plugin_dir,
        "external_channel",
        _channel_plugin("old"),
        kind="channel",
    )
    await _seed_resources(config, channel="external_channel", channel_path=events)
    lifecycle = ApplicationLifecycle(config, channel_factories={"mock": TestChannelFactory()})
    services = await lifecycle.start()

    await services.workflow.trigger("timed", session_id="old-run")
    assert (await services.workflow.wait("old-run")).status == "completed"
    assert events.read_text(encoding="utf-8").splitlines() == ["old-start", "old-send"]

    # Change the byte size as well as the content so import caches cannot reuse
    # bytecode written within the same filesystem timestamp tick.
    entry.write_text(_channel_plugin("new") + "\n", encoding="utf-8")
    report = await lifecycle.reload("plugins")
    assert report.errors == []
    assert events.read_text(encoding="utf-8").splitlines() == [
        "old-start",
        "old-send",
        "old-stop",
    ]

    await services.workflow.trigger("timed", session_id="new-run")
    assert (await services.workflow.wait("new-run")).status == "completed"
    assert events.read_text(encoding="utf-8").splitlines() == [
        "old-start",
        "old-send",
        "old-stop",
        "new-start",
        "new-send",
    ]
    await lifecycle.shutdown()


async def test_json_logging_rotates_and_redacts(tmp_path):
    path = tmp_path / "app.jsonl"
    sink = JsonLogSink(path, max_bytes=260, backup_count=1)
    sink.start()
    logger = logging.getLogger("logagent.lifecycle")
    try:
        for index in range(8):
            logger.info(
                "authorization=Bearer super-secret-token password=hidden-value",
                extra={
                    "event": f"event-{index}",
                    "session_id": "session-1",
                    "status": "available",
                },
            )
    finally:
        sink.close()

    assert path.exists()
    rotated = Path(str(path) + ".1")
    assert await asyncio.to_thread(rotated.exists)
    current = await asyncio.to_thread(path.read_text, encoding="utf-8")
    previous = await asyncio.to_thread(rotated.read_text, encoding="utf-8")
    content = current + previous
    assert "super-secret-token" not in content
    assert "hidden-value" not in content
    for line in content.splitlines():
        event = json.loads(line)
        assert {"time", "level", "module", "event", "message"} <= event.keys()

async def test_log_file_none_disables_logging_without_default_path(tmp_path):
    config = _config(tmp_path).model_copy(update={"log_file": None})
    lifecycle = ApplicationLifecycle(config, channel_factories={"mock": TestChannelFactory()})

    services = await lifecycle.start()
    try:
        assert services.log_path is None
        assert not (tmp_path / "data" / "logs" / "app.jsonl").exists()
        health = await lifecycle.health()
        assert health.status == "ready"
        logging_health = next(
            component for component in health.components if component.component == "logging"
        )
        assert logging_health.required is False
        assert logging_health.status == "available"
    finally:
        await lifecycle.shutdown()


async def test_resource_save_rebuilds_future_interval_plan(tmp_path):
    config = _config(tmp_path)
    await _seed_resources(config)
    lifecycle = ApplicationLifecycle(
        config,
        channel_factories={"mock": TestChannelFactory()},
    )
    services = await lifecycle.start()
    try:
        workflow = services.resources.get("workflows", "timed")
        services.resources.save(
            "workflows",
            WorkflowDefinition.model_validate({
                **workflow.model_dump(), "schedule": {"type": "every", "every_seconds": 25.0},
            }),
        )
        assert services.intervals.scheduler.get_job("timed").trigger.interval.total_seconds() == 25
    finally:
        await lifecycle.shutdown()


async def test_concurrent_start_and_shutdown_do_not_leak_resources(tmp_path):
    class BlockingSaver:
        is_setup = True

        async def setup(self):
            return None

        async def aget_tuple(self, config):
            return None

    class CheckpointerContext:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.exited = False

        async def __aenter__(self):
            self.entered.set()
            await self.release.wait()
            return BlockingSaver()

        async def __aexit__(self, exc_type, exc, traceback):
            self.exited = True

    config = _config(tmp_path).model_copy(update={"log_file": None})
    context = CheckpointerContext()
    lifecycle = ApplicationLifecycle(
        config,
        channel_factories={"mock": TestChannelFactory()},
        checkpointer_context_factory=lambda _: context,
    )

    start_task = asyncio.create_task(lifecycle.start())
    await asyncio.wait_for(context.entered.wait(), 5)
    shutdown_task = asyncio.create_task(lifecycle.shutdown())
    await asyncio.sleep(0)
    context.release.set()
    start_result, shutdown_result = await asyncio.gather(
        start_task, shutdown_task, return_exceptions=True
    )

    assert isinstance(start_result, LogAgentError)
    assert shutdown_result is None
    assert context.exited
    assert lifecycle._checkpointer_context is None
    assert lifecycle._session_store is None
    assert lifecycle._services is None
    assert lifecycle._shutdown_complete is True


async def test_cleanup_timeout_is_retried_without_closing_dependencies(tmp_path):
    class BlockingWorkflow:
        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def shutdown(self):
            self.started.set()
            await self.release.wait()

    class CloseProbe:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    workflow = BlockingWorkflow()
    ai = CloseProbe()
    lifecycle = ApplicationLifecycle(_config(tmp_path), shutdown_timeout=0.01)
    lifecycle._workflow = workflow
    lifecycle._ai = ai

    with pytest.raises(LogAgentError) as caught:
        await lifecycle.shutdown()
    assert caught.value.code == "lifecycle_shutdown_failed"
    assert caught.value.details["errors"][0]["code"] == "cleanup_timeout"
    assert workflow.started.is_set()
    assert ai.closed is False
    assert lifecycle._workflow is workflow

    workflow.release.set()
    await lifecycle.shutdown()
    assert ai.closed is True
    assert lifecycle._workflow is None
    assert lifecycle._ai is None
    assert lifecycle._shutdown_complete is True


async def test_pause_admission_timeout_does_not_stop_intervals_or_close_dependencies(tmp_path):
    class BlockingWorkflow:
        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.shutdown_called = False

        async def pause_admission(self):
            self.started.set()
            await self.release.wait()
            return 0

        async def shutdown(self):
            self.shutdown_called = True

    class IntervalProbe:
        def __init__(self):
            self.stopped = False

        async def stop(self):
            self.stopped = True

    class CloseProbe:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    workflow = BlockingWorkflow()
    intervals = IntervalProbe()
    ai = CloseProbe()
    lifecycle = ApplicationLifecycle(_config(tmp_path), shutdown_timeout=0.01)
    lifecycle._workflow = workflow
    lifecycle._intervals = intervals
    lifecycle._ai = ai

    with pytest.raises(LogAgentError) as caught:
        await lifecycle.shutdown()
    assert caught.value.code == "lifecycle_shutdown_failed"
    assert caught.value.details["errors"][0]["component"] == "workflow_pause_admission"
    assert workflow.started.is_set()
    assert intervals.stopped is False
    assert ai.closed is False
    assert lifecycle._intervals is intervals
    assert lifecycle._workflow is workflow

    workflow.release.set()
    await lifecycle.shutdown()
    assert intervals.stopped is True
    assert workflow.shutdown_called is True
    assert ai.closed is True
    assert lifecycle._intervals is None
    assert lifecycle._workflow is None
    assert lifecycle._shutdown_complete is True


async def test_health_failure_rejects_runs_and_recovers_after_local_check(tmp_path):
    config = _config(tmp_path).model_copy(update={"log_file": None})
    await _seed_resources(config)
    lifecycle = ApplicationLifecycle(config, channel_factories={"mock": TestChannelFactory()})
    services = await lifecycle.start()
    try:
        original_session_ids = services.session_store.session_ids
        calls = 0

        def flaky_session_ids():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("session store temporarily unavailable")
            return original_session_ids()

        services.session_store.session_ids = flaky_session_ids

        failed = await lifecycle.health()
        assert failed.status == "unavailable"
        assert failed.accepting_runs is False
        assert services.workflow.coordinator.accepting is False
        with pytest.raises(LogAgentError) as caught:
            await services.workflow.trigger("timed", session_id="rejected")
        assert caught.value.code == "not_ready"

        recovered = await lifecycle.health()
        assert recovered.status == "ready"
        assert recovered.accepting_runs is True
        assert services.workflow.coordinator.accepting is True
        await services.workflow.trigger("timed", session_id="recovered")
        assert (await services.workflow.wait("recovered")).status == "completed"
    finally:
        await lifecycle.shutdown()


async def test_cancelled_plugin_reload_finishes_without_partial_publish(tmp_path):
    config = _config(tmp_path)
    events = tmp_path / "channel-events.txt"
    entry = _write_plugin(
        config.plugin_dir,
        "external_channel",
        _channel_plugin("old"),
        kind="channel",
    )
    await _seed_resources(config, channel="external_channel", channel_path=events)
    lifecycle = ApplicationLifecycle(config, channel_factories={"mock": TestChannelFactory()})
    services = await lifecycle.start()
    try:
        await services.workflow.trigger("timed", session_id="old-run")
        assert (await services.workflow.wait("old-run")).status == "completed"
        entry.write_text(_channel_plugin("new") + "\n", encoding="utf-8")

        entered, release = asyncio.Event(), asyncio.Event()
        original_unload = services.channels.unload_owner

        async def blocked_unload(owner):
            entered.set()
            await release.wait()
            await original_unload(owner)

        services.channels.unload_owner = blocked_unload
        reload_task = asyncio.create_task(lifecycle.reload("plugins"))
        await asyncio.wait_for(entered.wait(), 5)
        reload_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reload_task

        assert services.workflow.coordinator.accepting is False
        assert services.intervals.paused is True
        release.set()

        report = await lifecycle.reload("plugins")
        assert report.errors == []
        assert services.workflow.coordinator.accepting is True
        assert services.intervals.paused is False
        await services.workflow.trigger("timed", session_id="new-run")
        assert (await services.workflow.wait("new-run")).status == "completed"
        assert events.read_text(encoding="utf-8").splitlines()[-2:] == [
            "new-start",
            "new-send",
        ]
    finally:
        release.set()
        await lifecycle.shutdown()


async def test_plugin_publish_failure_requires_explicit_successful_reload(tmp_path):
    config = _config(tmp_path)
    _write_plugin(config.plugin_dir, "external", _COLLECTOR_PLUGIN)
    await _seed_resources(config, collector="external")
    lifecycle = ApplicationLifecycle(config, channel_factories={"mock": TestChannelFactory()})
    services = await lifecycle.start()
    try:
        original_reload = services.channels.reload_register
        failed = False

        async def fail_once(channel_register):
            nonlocal failed
            if not failed:
                failed = True
                raise RuntimeError("channel publication failed")
            await original_reload(channel_register)

        services.channels.reload_register = fail_once
        with pytest.raises(RuntimeError, match="channel publication failed"):
            await lifecycle.reload("plugins")

        failed_health = await lifecycle.health()
        assert failed_health.status == "unavailable"
        assert failed_health.accepting_runs is False
        assert services.workflow.coordinator.accepting is False
        assert services.intervals.paused is True

        report = await lifecycle.reload("plugins")
        assert report.errors == []
        assert services.workflow.coordinator.accepting is True
        assert services.intervals.paused is False
        assert (await lifecycle.health()).status == "ready"
    finally:
        await lifecycle.shutdown()


@pytest.mark.parametrize("component", ["ai", "logging"])
async def test_health_reports_closed_component_and_disables_admission(tmp_path, component):
    lifecycle = ApplicationLifecycle(_config(tmp_path), channel_factories={})
    services = await lifecycle.start()
    try:
        if component == "ai":
            await services.ai.close()
        else:
            lifecycle._log_sink.close()

        report = await lifecycle.health()
        health = next(item for item in report.components if item.component == component)
        assert health.status == "unavailable"
        assert health.required is True
        assert health.error.code == (
            "logging_closed" if component == "logging" else "component_unavailable"
        )
        assert report.status == "unavailable"
        assert report.accepting_runs is False
        assert services.workflow.coordinator.accepting is False
    finally:
        await lifecycle.shutdown()


async def test_health_reports_log_probe_exception_and_recovers(tmp_path, monkeypatch):
    lifecycle = ApplicationLifecycle(_config(tmp_path), channel_factories={})
    services = await lifecycle.start()

    def broken_check():
        raise OSError("sensitive local path")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(lifecycle._log_sink, "check", broken_check)
            report = await lifecycle.health()
        health = next(item for item in report.components if item.component == "logging")
        assert health.error.code == "component_check_failed"
        assert health.error.details == {"component": "logging", "exception_type": "OSError"}
        assert report.accepting_runs is False
        assert services.workflow.coordinator.accepting is False
        assert (await lifecycle.health()).status == "ready"
        assert services.workflow.coordinator.accepting is True
    finally:
        await lifecycle.shutdown()
