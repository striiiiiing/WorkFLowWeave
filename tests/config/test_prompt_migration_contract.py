"""Prompt migration preserves edits and publishes only valid candidates."""

from copy import deepcopy
from pathlib import Path

import orjson
import pytest
from pydantic import ValidationError

from workflowweave.config import ResourceStore
from workflowweave.config.migrations import migrate_legacy_snapshot, migrate_resources
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import WorkflowSnapshot


def legacy_resource():
    return {
        "format_version": 2, "sources": {}, "channels": {},
        "ai": {"ai": {"id": "ai", "provider": "mock", "models": {"model": {}},
                      "system_prompt": "old system"}},
        "workflows": {"wf": {
            "id": "wf", "sources": ["source"],
            "source_overrides": {"source": {"source": {
                "id": "source", "call": {"kind": "cli", "mode": "argv", "executable": "printf"},
            }}},
            "analyses": [{"id": "task", "ai": "ai", "model": "model", "prompt": "analyze {input}"}],
            "fan_in": {"ai": "ai", "model": "model", "prompt": "summarize {input}"},
        }},
    }


def test_resource_migration_splits_layers_without_modifying_original():
    original = legacy_resource()
    before = deepcopy(original)
    migrated, changed = migrate_resources(original)
    workflow = migrated["workflows"]["wf"]
    assert changed and migrated["format_version"] == 4
    task = workflow["analyses"][0]
    assert (task["system_prompt"], task["input_prompt"], task["user_prompt"]) == (
        "old system", "{input}", "analyze",
    )
    assert workflow["fan_in"]["user_prompt"] == "summarize"
    assert workflow["fan_in"]["single_task_optimization"] is False
    assert original == before


def test_resource_migration_keeps_handwritten_layers_and_order():
    data = legacy_resource()
    workflow = data["workflows"]["wf"]
    workflow.update(system_prompt="shared", input_prompt="shared: {input}")
    task = workflow["analyses"][0]
    task.update(system_prompt="", input_prompt=None, user_prompt="my instruction {input}")
    fan = workflow["fan_in"]
    fan.update(system_prompt="my summary system", input_prompt="results: {input}",
               user_prompt="my summary instruction", order=["$input", "task"])
    migrated, _ = migrate_resources(data)
    current = migrated["workflows"]["wf"]
    assert current["system_prompt"] == "shared"
    assert current["input_prompt"] == "shared: {input}"
    assert current["analyses"][0] == {key: value for key, value in task.items() if key != "prompt"}
    for field in ("system_prompt", "input_prompt", "user_prompt", "order"):
        assert current["fan_in"][field] == fan[field]


def test_missing_difference_fails_without_overwriting_file_or_published_view(tmp_path):
    path = tmp_path / "resources.json"
    data = legacy_resource()
    path.write_bytes(orjson.dumps(data))
    store = ResourceStore(str(path))
    original = store.get("workflows", "wf")
    data["workflows"]["wf"]["analyses"][0]["prompt"] = "{input}"
    path.write_bytes(orjson.dumps(data))
    before = Path(store.location).read_bytes()
    with pytest.raises(WorkFLowWeaveError, match="差异指令") as error:
        store.reload_resources()
    assert error.value.code == "prompt_migration_required"
    assert path.read_bytes() == before
    assert store.get("workflows", "wf") == original
    data["workflows"]["wf"]["analyses"][0]["user_prompt"] = "handwritten fix"
    path.write_bytes(orjson.dumps(data))
    store.reload_resources()
    assert store.get("workflows", "wf").analyses[0].user_prompt == "handwritten fix"


def test_legacy_run_keeps_original_input_template_only_at_historical_boundary():
    data = legacy_resource()
    old = {"workflow": data["workflows"]["wf"], "ai": data["ai"],
           "sources": {"source": data["workflows"]["wf"]["source_overrides"]["source"]["source"]},
           "channels": {}, "created_at": "2026-10-06T00:00:00Z"}
    decoded = migrate_legacy_snapshot(old)
    with pytest.raises(ValidationError, match="user_prompt"):
        WorkflowSnapshot.model_validate(decoded)
    historical = WorkflowSnapshot.model_validate(decoded, context={"historical_snapshot": True})
    assert historical.workflow.analyses[0].input_prompt == "analyze {input}"
    assert historical.workflow.analyses[0].user_prompt == ""
    assert old["workflow"]["analyses"][0]["prompt"] == "analyze {input}"
