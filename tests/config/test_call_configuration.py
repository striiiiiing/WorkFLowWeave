from pathlib import Path

import pytest

from workflowweave.config.calls import normalize_call_options, resolve_channel_call, resolve_source_call
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import (
    ChannelConfig,
    ChannelOverride,
    SourceConfig,
    SourceOverride,
)
from workflowweave.schema import call_options_schema, validate_instance


def test_call_schema_projects_defaults_and_preserves_reference_types():
    schema = {
        "type": "object", "additionalProperties": False,
        "$defs": {"count": {"type": "integer", "minimum": 1}},
        "properties": {
            "path": {"type": "string", "description": "Account path"},
            "limit": {"$ref": "#/$defs/count", "description": "Count",
                      "x-workflowweave-workflow": True},
            "query": {"$ref": "#/properties/path", "description": "Search",
                      "x-workflowweave-workflow": True},
        },
        "required": ["path", "limit", "query"],
    }
    projected = call_options_schema(schema, {"path": "/private", "limit": 25})
    assert set(projected["properties"]) == {"limit", "query"}
    assert projected["required"] == ["query"]
    assert projected["properties"]["limit"]["default"] == 25
    assert projected["$defs"]["count"]["minimum"] == 1
    validate_instance({"query": "error"}, projected)
    with pytest.raises(WorkFLowWeaveError):
        validate_instance({"query": 1}, projected)
    with pytest.raises(WorkFLowWeaveError):
        validate_instance({"query": "error", "path": "/override"}, projected)
    assert "default" not in schema["properties"]["limit"]


def test_call_resolution_keeps_empty_arguments_and_shallow_overrides():
    source = SourceConfig(id="source", call={
        "kind": "mcp", "server": "saved", "tool": "echo",
        "arguments": {"values": ["instance"], "nested": {"a": 1}},
    }, limits={"item_tokens": 20})
    effective = resolve_source_call(source, {}, SourceOverride(
        arguments={"values": [], "nested": {"b": 2}},
        limits={"item_tokens": 5},
    ))
    assert effective.call.arguments == {"values": [], "nested": {"b": 2}}
    assert effective.limits.item_tokens == 5
    assert source.call.arguments == {"values": ["instance"], "nested": {"a": 1}}
    channel = ChannelConfig(id="mail", channel="mock", options={"path": "/fixed", "to": "old"})
    result = resolve_channel_call(channel, ChannelOverride(options={"to": "new"}))
    assert result.options == {"path": "/fixed", "to": "new"}
    assert channel.options["to"] == "old"


def test_call_normalization_rejects_instance_fields_and_does_not_apply_defaults():
    schema = {"type": "object", "properties": {
        "path": {"type": "string", "description": "Instance path", "x-workflowweave-path": True},
        "limit": {"type": "integer", "description": "Limit", "default": 200,
                  "x-workflowweave-workflow": True},
    }}
    assert normalize_call_options({}, schema, data_dir=Path("/data")) == {}
    with pytest.raises(WorkFLowWeaveError) as error:
        normalize_call_options({"path": "elsewhere"}, schema, data_dir=Path("/data"))
    assert error.value.details["errors"][0]["reason"] == "instance_only"
