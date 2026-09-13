import asyncio
import json
import math
import time
from copy import deepcopy

import pytest

from logagent.collection.manager import CollectorManager
from logagent.collection.mock import MockCollector
from logagent.config import PluginRegistry, expand_source
from logagent.errors import LogAgentError
from logagent.models import (
    CollectionContext,
    CollectorOutput,
    SetterTemplate,
    SourceConfig,
    SystemConfig,
)

CONTEXT = CollectionContext(workflow_id="workflow", session_id="session")


class FunctionCollector:
    name = "custom"
    description = "A Collector used to exercise the real registry and manager boundary"
    count_unit = "records"
    fields = []
    options_schema = {"type": "object", "additionalProperties": True}
    setters_schema = {"type": "object", "additionalProperties": False}

    def __init__(self, function):
        self.collect = function


async def manager_for(tmp_path, collector):
    registry = PluginRegistry([collector])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    return CollectorManager(registry.collectorRegister)


async def test_validate_is_pure_and_descriptions_are_independent(tmp_path):
    calls = []

    async def collect(options, setters, context):
        calls.append(context)
        raise AssertionError("validate must not execute collection")

    manager = await manager_for(tmp_path, FunctionCollector(collect))
    manager.validate(SourceConfig(id="one", collector="custom"))
    assert calls == []
    descriptions = manager.describe()
    descriptions[0].options_schema["additionalProperties"] = False
    descriptions[0].fields.append("changed")
    assert manager.describe()[0].options_schema["additionalProperties"] is True
    assert manager.describe()[0].fields == []
    with pytest.raises(LogAgentError):
        manager.validate(SourceConfig(id="one", collector="custom", setters={"undeclared": []}))
    assert calls == []


async def test_missing_collector_preserves_discovery_diagnostics_before_parameter_validation(
    tmp_path,
):
    plugin = tmp_path / "plugins" / "broken"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        json.dumps(
            {
                "id": "broken",
                "kind": "collector",
                "version": "1",
                "api_version": 1,
                "entry": {"backend": "absent.py"},
            }
        )
    )
    registry = PluginRegistry([])
    report = await registry.discover_plugins(SystemConfig(plugin_dir=str(plugin.parent)))
    assert len(report.errors) == 1
    manager = CollectorManager(registry.collectorRegister)
    source = SourceConfig(
        id="one", collector="broken", options={"unknown": True}, on_missing="skip"
    )
    with pytest.raises(LogAgentError) as caught:
        manager.validate(source)
    assert caught.value.code == "collector_missing"
    result = await manager.collect(source, CONTEXT)
    assert result.status == "missing" and result.source_id == "one"
    assert result.error.details["discovery_errors"][0]["details"]["plugin"] == "broken"
    assert result.items == [] and result.count == 0 and result.text == ""


async def test_setter_template_expansion_and_explicit_empty_override(tmp_path):
    mock = MockCollector()
    manager = await manager_for(tmp_path, mock)
    template = SetterTemplate(id="view", collector="mock", setters={"fields": ["message"]})
    source = SourceConfig(id="one", collector="mock", template="view", setters={"fields": []})
    with pytest.raises(LogAgentError) as caught:
        manager.validate(source)
    assert caught.value.code == "unresolved_template"
    normalized = expand_source(source, collector=mock, template=template)
    manager.validate(normalized)
    result = await manager.collect(normalized, CONTEXT)
    assert result.status == "filtered_empty"
    assert template.setters == {"fields": ["message"]}
    assert source.template == "view" and normalized.template is None
    with pytest.raises(LogAgentError):
        expand_source(
            source,
            collector=mock,
            template=SetterTemplate(id="view", collector="different", setters={}),
        )


@pytest.mark.parametrize("on_error", ["stop", "skip"])
async def test_runtime_bad_parameters_are_failed_facts_without_policy_execution(tmp_path, on_error):
    manager = await manager_for(tmp_path, MockCollector())
    source = SourceConfig(
        id="one", collector="mock", options={"invalid": "not-echoed"}, on_error=on_error
    )
    result = await manager.collect(source, CONTEXT)
    assert result.status == "failed" and result.error.code == "invalid_config"
    assert "not-echoed" not in result.model_dump_json()
    assert result.source_id == "one"


@pytest.mark.parametrize(
    "returned",
    [
        None,
        "some text",
        {"status": "success", "text": " ", "count": 1},
        {"status": "success", "text": "data", "count": True},
        {"status": "success", "text": "data", "count": 1.0},
        {"status": "success", "text": "data", "count": -1},
        {"status": "success", "text": "data", "count": 1, "metadata": {"bad": math.nan}},
        {"status": "success", "text": "data", "count": 1, "items": [{"bad": (1, 2)}]},
        {"status": "empty", "count": 1},
        {"status": "filtered_empty", "text": "unfinished"},
        {"status": "failed", "count": 0},
        {"status": "cancelled", "count": 0},
        {"status": "success", "text": "data", "count": 1, "source_id": "spoofed"},
    ],
)
async def test_illegal_plugin_output_is_failed_without_unfinished_data(tmp_path, returned):
    async def collect(options, setters, context):
        return deepcopy(returned)

    manager = await manager_for(tmp_path, FunctionCollector(collect))
    result = await manager.collect(SourceConfig(id="one", collector="custom"), CONTEXT)
    assert result.status == "failed"
    assert result.error.code == "invalid_collector_output"
    assert result.source_id == "one"
    assert result.items == [] and result.count == 0 and result.text == ""


async def test_constructed_and_mutated_models_cannot_bypass_output_validation(tmp_path):
    output = CollectorOutput.model_construct(status="success", text="data", count="1")

    async def collect(options, setters, context):
        return output

    manager = await manager_for(tmp_path, FunctionCollector(collect))
    result = await manager.collect(SourceConfig(id="one", collector="custom"), CONTEXT)
    assert result.status == "failed" and result.error.code == "invalid_collector_output"


async def test_plugin_exception_does_not_expose_credentials(tmp_path):
    async def collect(options, setters, context):
        raise RuntimeError("Authorization: Bearer do-not-echo")

    manager = await manager_for(tmp_path, FunctionCollector(collect))
    result = await manager.collect(SourceConfig(id="one", collector="custom"), CONTEXT)
    assert result.status == "failed" and result.error.code == "collection_failed"
    assert result.error.details["exception_type"] == "RuntimeError"
    assert "do-not-echo" not in result.model_dump_json()


async def test_total_timeout_runs_plugin_cleanup_and_drops_incomplete_content(tmp_path):
    closed = asyncio.Event()

    async def collect(options, setters, context):
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    manager = await manager_for(tmp_path, FunctionCollector(collect))
    result = await manager.collect(
        SourceConfig(id="one", collector="custom", timeout=0.02), CONTEXT
    )
    assert result.status == "timeout" and result.text == ""
    assert closed.is_set()


async def test_caller_cancellation_propagates_after_plugin_finally(tmp_path):
    started, closed = asyncio.Event(), asyncio.Event()

    async def collect(options, setters, context):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    manager = await manager_for(tmp_path, FunctionCollector(collect))
    task = asyncio.create_task(manager.collect(SourceConfig(id="one", collector="custom"), CONTEXT))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


async def test_one_source_timeout_does_not_cancel_other_sources(tmp_path):
    manager = await manager_for(tmp_path, MockCollector())
    timed, success = await asyncio.gather(
        manager.collect(
            SourceConfig(id="slow", collector="mock", options={"mode": "timeout"}, timeout=0.02),
            CONTEXT,
        ),
        manager.collect(SourceConfig(id="fast", collector="mock"), CONTEXT),
    )
    assert timed.status == "timeout" and success.status == "success"


async def test_validation_time_is_part_of_budget_and_collection_does_not_start_after_deadline(
    tmp_path,
):
    calls = []

    async def collect(options, setters, context):
        calls.append(True)
        return CollectorOutput(status="success", text="text", count=1)

    collector = FunctionCollector(collect)
    collector.validate = lambda options, setters: time.sleep(0.02)
    manager = await manager_for(tmp_path, collector)
    result = await manager.collect(
        SourceConfig(id="one", collector="custom", timeout=0.01), CONTEXT
    )
    assert result.status == "timeout" and calls == []


async def test_plugin_io_timeout_before_overall_deadline_is_a_source_failure(tmp_path):
    async def collect(options, setters, context):
        raise TimeoutError("private upstream request")

    manager = await manager_for(tmp_path, FunctionCollector(collect))
    result = await manager.collect(SourceConfig(id="one", collector="custom"), CONTEXT)
    assert result.status == "failed" and result.error.details["exception_type"] == "TimeoutError"


async def test_configuration_and_results_are_isolated_across_concurrent_instances(tmp_path):
    started = asyncio.Event()
    arrivals = []
    outputs = []

    async def collect(options, setters, context):
        arrivals.append(options["message"])
        if len(arrivals) == 2:
            started.set()
        await started.wait()
        message = options["message"]
        options["nested"]["value"] = "modified by plugin"
        output = CollectorOutput(
            status="success", text=message, items=[{"message": message}], count=1
        )
        outputs.append(output)
        return output

    manager = await manager_for(tmp_path, FunctionCollector(collect))
    sources = [
        SourceConfig(
            id=name, collector="custom", options={"message": name, "nested": {"value": "original"}}
        )
        for name in ("first", "second")
    ]
    results = await asyncio.gather(*(manager.collect(source, CONTEXT) for source in sources))
    for output in outputs:
        output.items[0]["message"] = "changed after return"
    assert [result.source_id for result in results] == ["first", "second"]
    assert [result.items[0]["message"] for result in results] == ["first", "second"]
    assert all(source.options["nested"]["value"] == "original" for source in sources)


async def test_mutated_source_cannot_hide_invalid_json(tmp_path):
    manager = await manager_for(tmp_path, MockCollector())
    source = SourceConfig(id="one", collector="mock")
    source.options["bad"] = math.nan
    result = await manager.collect(source, CONTEXT)
    assert result.status == "failed" and result.error.code == "invalid_config"


@pytest.mark.parametrize("phase", ["validate", "collect"])
async def test_plugin_structured_exceptions_cannot_bypass_redaction(tmp_path, phase):
    secret = "FAKE_SECRET_SENTINEL"

    def fail():
        raise LogAgentError("private_error", secret, {"authorization": secret})

    async def collect(options, setters, context):
        fail()

    collector = FunctionCollector(collect)
    if phase == "validate":
        collector.validate = lambda options, setters: fail()
    manager = await manager_for(tmp_path, collector)
    source = SourceConfig(id="one", collector="custom")
    if phase == "validate":
        with pytest.raises(LogAgentError) as caught:
            manager.validate(source)
        assert secret not in caught.value.info.model_dump_json()
    result = await manager.collect(source, CONTEXT)
    assert result.status == "failed"
    assert secret not in result.model_dump_json()


@pytest.mark.parametrize("cleanup", ["swallow", "raise"])
async def test_plugin_cleanup_cannot_swallow_caller_cancellation(tmp_path, cleanup):
    started = asyncio.Event()

    async def collect(options, setters, context):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if cleanup == "raise":
                raise RuntimeError("cleanup failed") from None
            return CollectorOutput(status="success", text="too late", count=1)

    manager = await manager_for(tmp_path, FunctionCollector(collect))
    task = asyncio.create_task(manager.collect(SourceConfig(id="one", collector="custom"), CONTEXT))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.parametrize("cleanup", ["swallow", "raise"])
async def test_plugin_cleanup_does_not_overwrite_an_exhausted_deadline(tmp_path, cleanup):
    async def collect(options, setters, context):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if cleanup == "raise":
                raise RuntimeError("cleanup failed") from None
            return CollectorOutput(status="success", text="too late", count=1)

    manager = await manager_for(tmp_path, FunctionCollector(collect))
    result = await manager.collect(
        SourceConfig(id="one", collector="custom", timeout=0.01), CONTEXT
    )
    assert result.status == "timeout"
    assert result.count == 0 and result.text == "" and result.items == []
