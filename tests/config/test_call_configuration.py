from pathlib import Path

import pytest

from logagent.config.calls import normalize_call_options, resolve_channel_call, resolve_source_call
from logagent.errors import LogAgentError
from logagent.models import (
    ChannelConfig,
    ChannelOverride,
    SetterTemplate,
    SourceConfig,
    SourceOverride,
)
from logagent.schema import call_options_schema, validate_instance


def test_call_schema_projects_defaults_and_preserves_reference_types():
    schema = {
        "type": "object", "additionalProperties": False,
        "$defs": {"count": {"type": "integer", "minimum": 1}},
        "properties": {
            "path": {"type": "string", "description": "Account path"},
            "limit": {"$ref": "#/$defs/count", "description": "Count",
                      "x-logagent-workflow": True},
            "query": {"$ref": "#/properties/path", "description": "Search",
                      "x-logagent-workflow": True},
        },
        "required": ["path", "limit", "query"],
    }
    projected = call_options_schema(schema, {"path": "/private", "limit": 25})
    assert set(projected["properties"]) == {"limit", "query"}
    assert projected["required"] == ["query"]
    assert projected["properties"]["limit"]["default"] == 25
    assert projected["$defs"]["count"]["minimum"] == 1
    validate_instance({"query": "error"}, projected)
    with pytest.raises(LogAgentError):
        validate_instance({"query": 1}, projected)
    with pytest.raises(LogAgentError):
        validate_instance({"query": "error", "path": "/override"}, projected)
    assert "default" not in schema["properties"]["limit"]


def test_call_resolution_keeps_empty_setters_and_replaces_whole_options():
    source = SourceConfig(id="source", collector="mock", template="saved",
                          setters={"values": ["instance"]}, options={"nested": {"a": 1}})
    templates = {key: SetterTemplate(id=key, collector="mock", setters={"values": [key]})
                 for key in ("saved", "call")}
    effective = resolve_source_call(source, templates, SourceOverride(
        template="call", setters={"values": []}, options={"nested": {"b": 2}},
    ))
    assert effective.setters == {"values": []}
    assert effective.options == {"nested": {"b": 2}}
    assert effective.template is None and source.template == "saved"
    channel = ChannelConfig(id="mail", channel="mock", options={"path": "/fixed", "to": "old"})
    result = resolve_channel_call(channel, ChannelOverride(options={"to": "new"}))
    assert result.options == {"path": "/fixed", "to": "new"}
    assert channel.options["to"] == "old"


def test_call_normalization_rejects_instance_fields_and_does_not_apply_defaults():
    schema = {"type": "object", "properties": {
        "path": {"type": "string", "description": "Instance path", "x-logagent-path": True},
        "limit": {"type": "integer", "description": "Limit", "default": 200,
                  "x-logagent-workflow": True},
    }}
    assert normalize_call_options({}, schema, data_dir=Path("/data")) == {}
    with pytest.raises(LogAgentError) as error:
        normalize_call_options({"path": "elsewhere"}, schema, data_dir=Path("/data"))
    assert error.value.details["errors"][0]["reason"] == "instance_only"
