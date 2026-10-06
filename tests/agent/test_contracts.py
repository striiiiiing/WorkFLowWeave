from copy import deepcopy

import pytest
from pydantic import ValidationError

from workflowweave.agent.config import AgentConfig
from workflowweave.agent.contracts import freeze


def test_turn_config_freezes_nested_values_and_retains_original_defaults():
    original = AgentConfig()
    snapshot = freeze(original)
    assert snapshot.model_dump() == original.model_dump()
    with pytest.raises(ValidationError):
        snapshot.output_tokens = 123
    with pytest.raises(ValidationError):
        snapshot.sandbox.enabled = False
    original.sandbox.enabled = False
    assert snapshot.sandbox.enabled is True


def test_tool_schema_snapshot_is_deeply_immutable_and_json_compatible():
    import json

    original = {"properties": {"value": {"enum": ["a", "b"]}}}
    snapshot = freeze(original)
    original["properties"]["value"]["enum"].append("c")
    assert json.loads(json.dumps(snapshot)) == {"properties": {"value": {"enum": ["a", "b"]}}}
    with pytest.raises(TypeError):
        snapshot["properties"]["value"]["enum"].append("d")
    with pytest.raises(TypeError):
        snapshot["properties"]["other"] = {}
    assert deepcopy(snapshot) is snapshot
