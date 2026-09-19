import math
from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from logagent.errors import LogAgentError
from logagent.models import (
    CollectionContext,
    CollectorOutput,
    ErrorInfo,
    JSONValue,
    SourceConfig,
    SystemConfig,
)
from logagent.schema import schema_defaults, validate_instance, validate_schema


@pytest.mark.parametrize("timeout", ["invalid", 0, -1, math.inf, math.nan])
def test_seconds_are_positive_and_finite(timeout):
    with pytest.raises(ValidationError):
        SourceConfig(id="source", collector="mock", timeout=timeout)


@pytest.mark.parametrize("identifier", ["../source", "bad/id", "", "a" * 81, "a\n", "中文"])
def test_identifiers_are_not_paths(identifier):
    with pytest.raises(ValidationError):
        SourceConfig(id=identifier, collector="mock")


@pytest.mark.parametrize("value", [math.nan, math.inf, {1: "value"}, (1, 2), datetime.now(UTC)])
def test_extension_data_is_json(value):
    with pytest.raises(ValidationError):
        SourceConfig(id="source", collector="mock", options={"data": value})


def test_top_level_fields_forbid_extras_and_copy_extension_data():
    with pytest.raises(ValidationError):
        SourceConfig(id="source", collector="mock", unknown=True)
    with pytest.raises(ValidationError):
        SystemConfig(port=0)
    options = {"records": [{"message": "before"}]}
    source = SourceConfig(id="source", collector="mock", options=options)
    options["records"][0]["message"] = "after"
    assert source.options["records"][0]["message"] == "before"
    assert SourceConfig(id="other", collector="mock").options == {}
    assert SourceConfig.model_validate_json(source.model_dump_json()) == source


@pytest.mark.parametrize(
    "data",
    [
        {"status": "success", "count": 1, "text": " "},
        {"status": "success", "count": True, "text": "text"},
        {"status": "success", "count": 0, "text": "text"},
        {"status": "empty", "count": 1},
        {"status": "filtered_empty", "items": [{"a": 1}]},
        {"status": "failed"},
        {"status": "cancelled"},
        {"status": "missing", "count": -1},
        {"status": "empty", "error": ErrorInfo(code="error", message="error")},
    ],
)
def test_output_states_cannot_hide_failures_or_partial_text(data):
    with pytest.raises(ValidationError):
        CollectorOutput.model_validate(data)


def test_context_is_separate_from_persistent_models():
    context = CollectionContext(workflow_id="workflow", session_id="session")
    assert not hasattr(context, "model_dump")
    with pytest.raises(ValueError):
        CollectionContext(workflow_id="../workflow", session_id="session")


def test_schema_validation_is_strict_non_mutating_and_does_not_echo_values():
    schema = {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
                "description": "Selected names",
            }
        },
        "additionalProperties": False,
    }
    validate_schema(schema)
    validate_instance({"names": []}, schema)
    defaults = schema_defaults(schema)
    defaults["names"].append("changed")
    assert schema["properties"]["names"]["default"] == []
    with pytest.raises(LogAgentError) as caught:
        validate_instance({"secret": "do-not-echo-this"}, schema, path=["options"])
    assert caught.value.details["errors"][0]["path"] == ["options"]
    assert "do-not-echo-this" not in caught.value.info.model_dump_json()


def test_partial_defaults_keep_nested_requirements():
    schema = {
        "type": "object",
        "properties": {"nested": {"type": "object", "required": ["value"]}},
        "required": ["nested"],
    }
    validate_instance({}, schema, partial=True)
    with pytest.raises(LogAgentError):
        validate_instance({"nested": {}}, schema, partial=True)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array"},
        {"type": "object", "properties": {"x": {"type": "made-up"}}},
        {"type": "object", "$ref": "https://example.invalid/schema.json"},
    ],
)
def test_invalid_and_remote_schemas_rejected(schema):
    with pytest.raises(LogAgentError):
        validate_schema(schema)


def test_json_value_validates_nested_containers_without_pydantic_context():
    adapter = TypeAdapter(JSONValue)
    assert adapter.validate_python({"values": [1, True, None]}) == {"values": [1, True, None]}
    with pytest.raises(ValidationError):
        adapter.validate_python({"invalid": math.nan})


def test_partial_defaults_resolve_local_references():
    schema = {
        "type": "object",
        "$ref": "#/$defs/settings",
        "$defs": {"settings": {"type": "object", "required": ["name"]}},
    }
    validate_instance({}, schema, partial=True)
    with pytest.raises(LogAgentError):
        validate_instance({}, schema)


def test_schema_default_data_is_not_treated_as_a_remote_reference():
    validate_schema(
        {
            "type": "object",
            "properties": {
                "record": {
                    "type": "object",
                    "description": "A user record",
                    "default": {"$ref": "https://example.invalid/content"},
                }
            },
        }
    )


def test_schema_fields_require_type_and_description():
    with pytest.raises(LogAgentError):
        validate_schema({"type": "object", "properties": {"value": {"type": "string"}}})


def option_schema(rule, *, definitions=None):
    return {
        "type": "object",
        "properties": {"value": {"description": "Configurable value", **rule}},
        "$defs": definitions or {},
        "additionalProperties": False,
    }


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
@pytest.mark.parametrize("reference", ["#/$defs/missing", "#missing_anchor"])
def test_optional_local_references_must_resolve_before_instances_exist(keyword, reference):
    with pytest.raises(LogAgentError) as caught:
        validate_schema(option_schema({keyword: reference}))
    assert caught.value.code == "invalid_schema"


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
def test_references_in_unused_definitions_are_also_checked(keyword):
    schema = option_schema({"type": "string"}, definitions={"unused": {keyword: "#/$defs/missing"}})
    with pytest.raises(LogAgentError):
        validate_schema(schema)


def test_local_json_pointer_unescapes_definition_names():
    schema = option_schema(
        {"$ref": "#/$defs/value~1name~0"},
        definitions={"value/name~": {"type": "integer"}},
    )
    validate_schema(schema)
    validate_instance({"value": 3}, schema)
    with pytest.raises(LogAgentError) as caught:
        validate_instance({"value": "wrong"}, schema)
    assert caught.value.code == "invalid_config"


@pytest.mark.parametrize(
    ("reference_keyword", "anchor_keyword"),
    [("$ref", "$anchor"), ("$dynamicRef", "$dynamicAnchor")],
)
def test_local_plain_and_dynamic_anchors(reference_keyword, anchor_keyword):
    schema = option_schema(
        {reference_keyword: "#value_type"},
        definitions={"value": {anchor_keyword: "value_type", "type": "string"}},
    )
    validate_schema(schema)
    validate_instance({"value": "ok"}, schema)
    with pytest.raises(LogAgentError):
        validate_instance({"value": 3}, schema)


def test_nested_resource_reference_uses_its_local_id_scope():
    schema = option_schema(
        {"$ref": "#/$defs/settings"},
        definitions={
            "settings": {
                "$id": "settings.json",
                "type": "object",
                "properties": {"count": {"$ref": "#/$defs/count"}},
                "$defs": {"count": {"type": "integer"}},
            }
        },
    )
    schema["$id"] = "https://example.invalid/root.json"
    validate_schema(schema)
    validate_instance({"value": {"count": 1}}, schema)
    with pytest.raises(LogAgentError):
        validate_instance({"value": {"count": "wrong"}}, schema)


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
def test_remote_references_are_rejected_without_network_or_value_disclosure(keyword, monkeypatch):
    def unexpected_network(*args, **kwargs):
        raise AssertionError("Schema validation must not access the network")

    monkeypatch.setattr("socket.create_connection", unexpected_network)
    schema = option_schema({keyword: "https://example.invalid/FAKE_SECRET_SCHEMA"})
    with pytest.raises(LogAgentError) as caught:
        validate_schema(schema)
    assert "FAKE_SECRET_SCHEMA" not in caught.value.info.model_dump_json()


@pytest.mark.parametrize("annotation", ["default", "examples", "const", "enum"])
def test_annotation_values_are_not_walked_for_references(annotation):
    data = {"$ref": "https://example.invalid/data", "$dynamicRef": "#not_an_anchor"}
    value = [data] if annotation in ("examples", "enum") else data
    schema = option_schema({"type": "object", annotation: value})
    validate_schema(schema)


def test_reference_target_must_itself_be_a_valid_schema():
    schema = option_schema({"$ref": "#/examples/0"})
    schema["examples"] = ["not a schema"]
    with pytest.raises(LogAgentError):
        validate_schema(schema)
    schema["examples"] = [{"type": "unsupported_type"}]
    with pytest.raises(LogAgentError):
        validate_schema(schema)


@pytest.mark.parametrize(
    "rule",
    [
        {"allOf": [{}]},
        {"anyOf": [{"type": "string"}, {}]},
        {"oneOf": [{"type": "string"}, True]},
        {"$ref": "#/$defs/untyped"},
        {"anyOf": [{"type": "null"}, {"$ref": "#/$defs/untyped"}]},
    ],
)
def test_combinators_and_references_cannot_bypass_field_type_declarations(rule):
    with pytest.raises(LogAgentError):
        validate_schema(option_schema(rule, definitions={"untyped": {}}))


@pytest.mark.parametrize(
    "rule",
    [
        {"allOf": [{"minLength": 1}, {"type": "string"}]},
        {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        {"oneOf": [{"type": "string"}, {"$ref": "#/$defs/count"}]},
        {"anyOf": [False, {"type": "string"}]},
        {"oneOf": [{"type": "string"}, False]},
        {"type": "string", "anyOf": [{"minLength": 1}, {"maxLength": 4}]},
    ],
)
def test_valid_combinations_provide_types_without_requiring_types_on_all_conjuncts(rule):
    validate_schema(option_schema(rule, definitions={"count": {"type": "integer"}}))


@pytest.mark.parametrize("keyword", ["anyOf", "oneOf"])
def test_reference_to_false_is_not_a_valid_untyped_alternative(keyword):
    schema = option_schema(
        {keyword: [{"$ref": "#/$defs/disabled"}, {"type": "string"}]},
        definitions={"disabled": False},
    )
    validate_schema(schema)
    validate_instance({"value": "ok"}, schema)
    with pytest.raises(LogAgentError):
        validate_instance({"value": 1}, schema)


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
def test_typed_recursive_object_reference_accepts_finite_data(keyword):
    anchor = "$dynamicAnchor" if keyword == "$dynamicRef" else "$anchor"
    schema = option_schema(
        {keyword: "#node"},
        definitions={
            "node": {
                anchor: "node",
                "type": "object",
                "properties": {"children": {"type": "array", "items": {keyword: "#node"}}},
            }
        },
    )
    validate_schema(schema)
    validate_instance({"value": {"children": [{"children": []}]}}, schema)
    with pytest.raises(LogAgentError):
        validate_instance({"value": {"children": [3]}}, schema)


def test_recursive_alias_can_reach_a_real_type_declaration():
    schema = option_schema(
        {"$ref": "#/$defs/alias"},
        definitions={
            "alias": {"$ref": "#/$defs/node"},
            "node": {
                "type": "object",
                "properties": {"next": {"$ref": "#/$defs/alias"}},
            },
        },
    )
    validate_schema(schema)
    validate_instance({"value": {"next": {"next": {}}}}, schema)


@pytest.mark.parametrize("referenced", [True, False])
def test_pure_reference_cycles_are_rejected_even_if_unused(referenced):
    schema = option_schema(
        {"$ref": "#/$defs/first"} if referenced else {"type": "string"},
        definitions={
            "first": {"$ref": "#/$defs/second"},
            "second": {"allOf": [{"$ref": "#/$defs/first"}, {"minLength": 1}]},
        },
    )
    with pytest.raises(LogAgentError) as caught:
        validate_schema(schema)
    assert caught.value.code == "invalid_schema"


def test_type_in_one_alternative_does_not_ground_an_independent_untyped_cycle():
    schema = option_schema(
        {"anyOf": [{"type": "string"}, {"$ref": "#/$defs/loop"}]},
        definitions={"loop": {"$ref": "#/$defs/loop"}},
    )
    with pytest.raises(LogAgentError):
        validate_schema(schema)


@pytest.mark.parametrize("keyword", ["anyOf", "oneOf"])
def test_self_reference_cannot_mask_an_untyped_alternative(keyword):
    schema = option_schema(
        {"$ref": "#/$defs/node"},
        definitions={"node": {"$ref": "#/$defs/node", keyword: [{"type": "string"}, {}]}},
    )
    with pytest.raises(LogAgentError):
        validate_schema(schema)


def test_partial_defaults_still_check_nested_requirements_through_anchors():
    schema = option_schema(
        {"$ref": "#nested"},
        definitions={"nested": {"$anchor": "nested", "type": "object", "required": ["name"]}},
    )
    schema["required"] = ["value"]
    validate_schema(schema)
    validate_instance({}, schema, partial=True)
    with pytest.raises(LogAgentError):
        validate_instance({"value": {}}, schema, partial=True)


@pytest.mark.parametrize("value", [2**64, -(2**63) - 1, "\ud800", {"nested": -math.inf}])
def test_json_value_rejects_orjson_boundaries(value):
    with pytest.raises(ValidationError):
        TypeAdapter(JSONValue).validate_python(value)


def test_json_value_handles_integer_boundaries_and_cycles():
    adapter = TypeAdapter(JSONValue)
    value = {"integers": [-(2**63), 2**64 - 1]}
    assert adapter.validate_python(value) == value
    cycle = []
    cycle.append(cycle)
    with pytest.raises(ValidationError):
        adapter.validate_python(cycle)
