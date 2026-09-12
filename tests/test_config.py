import asyncio
import json
import os

import pytest
from pydantic import ValidationError

from logagent.config import ResourceStore, load_plugin_config, load_system_config
from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    AnalysisTask,
    BackupPolicy,
    ChannelConfig,
    CollectionResult,
    FanInConfig,
    SessionRecord,
    SetterTemplate,
    SourceConfig,
    SystemConfig,
    WorkflowDefinition,
)


@pytest.mark.parametrize("identifier", ["", "../escape", "has space", "中", "x" * 81, "a/b", "a\\\\b"])
def test_invalid_ids_are_rejected(identifier):
    with pytest.raises(ValidationError):
        SourceConfig(id=identifier, collector="mock")


@pytest.mark.parametrize(
    "options",
    [
        {"temperature": 0.5},
        {"top_k": 2},
        {"extra": {"temperature": 1}},
        {"nested": [{"top_k": 2}]},
        {"messages": []},
        {"api_key": "not-a-real-key"},
        {"value": float("nan")},
        {"value": float("inf")},
        {"object": object()},
    ],
)
def test_unsupported_or_non_json_model_options_are_rejected(options):
    with pytest.raises(ValidationError):
        AIConfig(id="test", model_options=options)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True, False, "5"])
def test_invalid_timeouts_are_rejected(value):
    with pytest.raises(ValidationError):
        SourceConfig(id="test", collector="mock", timeout=value)


@pytest.mark.parametrize("value", ["true", "false", "yes", 0, 1])
def test_configuration_switches_reject_non_booleans(value):
    with pytest.raises(ValidationError):
        ChannelConfig(id="test", channel="file", enabled=value)
    with pytest.raises(ValidationError):
        BackupPolicy(enabled=value)


def test_unknown_fields_and_duplicate_references_are_rejected():
    with pytest.raises(ValidationError):
        AIConfig(id="test", temperature=1)
    with pytest.raises(ValidationError):
        SystemConfig(base_dir="/arbitrary")
    with pytest.raises(ValidationError):
        WorkflowDefinition(id="wf", sources=["s", "s"], analyses=[AnalysisTask(id="a", ai="model")])
    with pytest.raises(ValidationError):
        WorkflowDefinition(
            id="wf", sources=["s"], analyses=[AnalysisTask(id="a", ai="model")], fan_in=FanInConfig(order=["unknown"])
        )
    with pytest.raises(ValidationError):
        FanInConfig(order=["$input", "$input"])
    with pytest.raises(ValidationError):
        BackupPolicy(stages=["analysis", "analysis"])
    with pytest.raises(ValidationError):
        WorkflowDefinition(
            id="wf", sources=["s"], analyses=[AnalysisTask(id="a", ai="model")], analysis_concurrency=True
        )


@pytest.mark.asyncio
async def test_config_paths_are_anchored_to_file_not_cwd(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"data_dir": "data", "plugin_dir": "plugins", "log_file": "logs/app.log"}))
    different = tmp_path / "elsewhere"
    different.mkdir()
    first = await load_system_config(config_file)
    monkeypatch.chdir(different)
    second = await load_system_config(config_file)
    assert first.model_dump() == second.model_dump()
    assert second.data_dir == tmp_path / "data"
    assert second.plugin_dir == tmp_path / "plugins"
    assert second.log_file == tmp_path / "logs/app.log"
    assert second.base_dir == tmp_path
    assert "base_dir" not in second.model_dump()


@pytest.mark.asyncio
async def test_invalid_json_and_missing_config_are_distinct(tmp_path):
    with pytest.raises(LogAgentError) as missing:
        await load_system_config(tmp_path / "missing.json")
    assert missing.value.code == "CONFIG_NOT_FOUND"
    path = tmp_path / "bad.json"
    path.write_text("{")
    with pytest.raises(LogAgentError) as invalid:
        await load_system_config(path)
    assert invalid.value.code == "CONFIG_INVALID_JSON"


@pytest.mark.asyncio
async def test_validation_errors_identify_fields_without_echoing_values(tmp_path):
    store = ResourceStore(tmp_path)
    with pytest.raises(LogAgentError) as error:
        await store.save("sources", {"id": "source", "collector": "mock", "timeout": "example-private-value"})
    assert error.value.code == "VALIDATION_ERROR"
    assert error.value.details["errors"][0]["path"] == ["sources", "timeout"]
    assert "example-private-value" not in json.dumps(error.value.as_dict())
    assert await store.list("sources") == []


@pytest.mark.asyncio
async def test_malformed_model_url_cannot_leak_credentials_in_errors(tmp_path):
    store = ResourceStore(tmp_path)
    with pytest.raises(LogAgentError) as error:
        await store.save("ai", {"id": "model", "base_url": "https://user:EXAMPLE_SECRET@host／name/v1"})
    assert error.value.code == "VALIDATION_ERROR"
    assert error.value.details["errors"][0]["path"] == ["ai", "base_url"]
    assert "EXAMPLE_SECRET" not in json.dumps(error.value.as_dict())


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["data_dir", "plugin_dir", "log_file"])
async def test_invalid_system_paths_return_structured_field_errors(tmp_path, field):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({field: "a\u0000b"}))
    with pytest.raises(LogAgentError) as error:
        await load_system_config(path)
    assert error.value.code == "VALIDATION_ERROR"
    assert error.value.details["errors"][0]["path"] == [field]


@pytest.mark.asyncio
async def test_plugin_configuration_is_optional_independent_and_diagnostic(tmp_path):
    missing = tmp_path / "missing.json"
    assert await load_plugin_config(missing) == {}
    assert not missing.exists()

    invalid = tmp_path / "broken.json"
    invalid.write_text('{"key": "example-private-value",')
    valid = tmp_path / "healthy.json"
    valid.write_text(json.dumps({"sources": [{"name": "sample"}], "data_dir": "plugin-only"}))
    outcomes = await asyncio.gather(load_plugin_config(invalid), load_plugin_config(valid), return_exceptions=True)
    assert isinstance(outcomes[0], LogAgentError)
    assert outcomes[0].code == "PLUGIN_CONFIG_INVALID"
    assert outcomes[0].details == {"file": "broken.json"}
    assert "example-private-value" not in json.dumps(outcomes[0].as_dict())
    outcomes[1]["sources"][0]["name"] = "changed"
    assert (await load_plugin_config(valid))["sources"][0]["name"] == "sample"

    system = tmp_path / "config.json"
    system.write_text("{}")
    assert (await load_system_config(system)).data_dir == tmp_path / "data"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["[]", "null", "true", '{"nested": {"number": NaN}}', '{"number": 1e999}'])
async def test_plugin_configuration_rejects_invalid_objects(tmp_path, content):
    path = tmp_path / "plugin.json"
    path.write_text(content)
    with pytest.raises(LogAgentError) as error:
        await load_plugin_config(path)
    assert error.value.code == "PLUGIN_CONFIG_INVALID"


@pytest.mark.asyncio
async def test_all_resource_kinds_persist_and_snapshot_covers_fan_in(tmp_path):
    store = ResourceStore(tmp_path / "resources", base_dir=tmp_path)
    await store.save(
        "setters", SetterTemplate(id="base", collector="mock", setters={"fields": ["old"], "group_by": "group"})
    )
    await store.save(
        "sources",
        SourceConfig(
            id="source", collector="mock", template="base", setters={"fields": ["new"]}, options={"path": "source.txt"}
        ),
    )
    await store.save("ai", AIConfig(id="branch"))
    await store.save("ai", AIConfig(id="aggregate", api_key_env="EXAMPLE_KEY"))
    await store.save("channels", ChannelConfig(id="file", channel="file", options={"path": "reports/out.md"}))
    workflow = WorkflowDefinition(
        id="wf",
        sources=["source"],
        analyses=[AnalysisTask(id="a", ai="branch")],
        fan_in=FanInConfig(ai="aggregate"),
        channels=["file"],
    )
    await store.save("workflows", workflow)
    snapshot = await ResourceStore(tmp_path / "resources", base_dir=tmp_path).snapshot("wf")
    assert set(snapshot.ai) == {"branch", "aggregate"}
    assert snapshot.ai["aggregate"].api_key_env == "EXAMPLE_KEY"
    assert snapshot.sources["source"].setters == {"fields": ["new"], "group_by": "group"}
    assert snapshot.sources["source"].options["path"] == "source.txt"
    assert snapshot.channels["file"].options["path"] == str(tmp_path / "reports/out.md")
    assert (await store.get("channels", "file")).options["path"] == "reports/out.md"
    for kind, identifier in [("sources", "source"), ("setters", "base"), ("ai", "aggregate"), ("channels", "file")]:
        with pytest.raises(LogAgentError) as referenced:
            await store.delete(kind, identifier)
        assert referenced.value.code == "CONFLICT"
    await store.delete("workflows", "wf")
    await store.delete("sources", "source")
    await store.delete("setters", "base")
    assert await store.list("setters") == []


@pytest.mark.asyncio
async def test_invalid_references_never_create_a_file(tmp_path):
    store = ResourceStore(tmp_path)
    with pytest.raises(LogAgentError):
        await store.save("sources", SourceConfig(id="invalid", collector="mock", template="missing"))
    assert not (tmp_path / "sources" / "invalid.json").exists()
    with pytest.raises(LogAgentError):
        await store.save(
            "workflows", WorkflowDefinition(id="wf", sources=["missing"], analyses=[AnalysisTask(id="a", ai="missing")])
        )
    with pytest.raises(LogAgentError):
        await store.save("sources", AIConfig(id="wrong"))
    with pytest.raises(LogAgentError):
        await store.get("sources", "../escape")


@pytest.mark.asyncio
async def test_atomic_replace_failure_preserves_previous_json(tmp_path, monkeypatch):
    store = ResourceStore(tmp_path)
    await store.save("ai", AIConfig(id="model", model="old"))

    def fail(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(LogAgentError) as error:
        await store.save("ai", AIConfig(id="model", model="new"))
    assert error.value.code == "CONFIG_UNAVAILABLE"
    assert (await store.get("ai", "model")).model == "old"
    assert list((tmp_path / "ai").iterdir()) == [tmp_path / "ai" / "model.json"]


@pytest.mark.asyncio
async def test_corrupt_resources_do_not_silently_disappear(tmp_path):
    store = ResourceStore(tmp_path)
    await store.save("ai", AIConfig(id="model"))
    (tmp_path / "ai" / "model.json").write_text("not json")
    with pytest.raises(LogAgentError) as error:
        await store.list("ai")
    assert error.value.code == "RESOURCE_CORRUPT"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{", "invalid_json"),
        ('{"id":"model","unexpected":true}', "invalid_schema"),
        ('{"id":"other"}', "id_mismatch"),
    ],
)
async def test_corrupt_resources_report_distinct_causes(tmp_path, content, reason):
    store = ResourceStore(tmp_path)
    await store.save("ai", AIConfig(id="model"))
    (tmp_path / "ai" / "model.json").write_text(content)
    with pytest.raises(LogAgentError) as error:
        await store.get("ai", "model")
    assert error.value.code == "RESOURCE_CORRUPT"
    assert error.value.details["id"] == "model"
    assert error.value.details["reason"] == reason


@pytest.mark.asyncio
async def test_resource_directory_failure_is_not_an_empty_list(tmp_path):
    store = ResourceStore(tmp_path)
    assert await store.list("ai") == []
    (tmp_path / "ai").write_text("not a directory")
    with pytest.raises(LogAgentError) as error:
        await store.list("ai")
    assert error.value.code == "CONFIG_UNAVAILABLE"


@pytest.mark.asyncio
async def test_resource_symlinks_cannot_escape_storage(tmp_path):
    store = ResourceStore(tmp_path / "resources")
    await store.save("ai", AIConfig(id="model"))
    outside = tmp_path / "outside.json"
    outside.write_text('{"id":"escape"}')
    (store.root / "ai" / "escape.json").symlink_to(outside)
    for operation in (store.get("ai", "escape"), store.save("ai", AIConfig(id="escape")), store.delete("ai", "escape")):
        with pytest.raises(LogAgentError) as error:
            await operation
        assert error.value.code == "VALIDATION_ERROR"
    assert outside.read_text() == '{"id":"escape"}'


@pytest.mark.asyncio
async def test_concurrent_saves_are_complete_and_return_independent_objects(tmp_path):
    store = ResourceStore(tmp_path)
    await asyncio.gather(*(store.save("ai", AIConfig(id=f"m{i}")) for i in range(12)))
    models = await store.list("ai")
    assert len(models) == 12
    models[0].model_options["local"] = "change"
    assert (await store.get("ai", models[0].id)).model_options == {}
    with pytest.raises(LogAgentError) as error:
        await store.save("ai", AIConfig(id="missing"), mode="replace")
    assert error.value.code == "NOT_FOUND"


def test_management_records_do_not_contain_stage_bodies():
    record = SessionRecord(
        id="s", workflow_id="wf", source_statuses={"a": "empty", "b": "filtered_empty", "c": "failed"}
    )
    assert set(record.source_statuses.values()) == {"empty", "filtered_empty", "failed"}
    assert record.output_frozen is False
    assert "text" not in record.model_dump()
    assert record.created_at.tzinfo is not None
    with pytest.raises(ValidationError):
        CollectionResult(source_id="s", status="pretend_success")
