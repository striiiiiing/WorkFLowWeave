"""共享 Schema 注解遍历测试。

构造含引用、组合分支、递归对象与数组的 schema，注入凭据/路径转换函数，
断言仅匹配分支转换、同一值不重复转换、未知字段保留给后续校验。
使用真实 schema 解析与内存数据，不读取凭据或访问网络。
"""

from copy import deepcopy
from pathlib import Path

import pytest

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.schema import transform_annotations, validate_instance, validate_schema


def normalize(value, rule):
    if rule.get("x-workflowweave-credential") and isinstance(value, str):
        raise WorkFLowWeaveError("invalid_credential", "Plaintext credential")
    if rule.get("x-workflowweave-path"):
        return str(Path("/data") / value)
    return value


def test_reference_annotations_reject_plaintext_and_fix_paths():
    schema = {
        "type": "object",
        "properties": {
            "path": {"$ref": "#/$defs/path", "description": "Output path"},
            "secret": {"$ref": "#/$defs/secret", "description": "Credential"},
        },
        "$defs": {
            "path": {"type": "string", "x-workflowweave-path": True},
            "secret": {"type": ["string", "object"], "x-workflowweave-credential": True},
        },
        "additionalProperties": False,
    }
    validate_schema(schema)
    with pytest.raises(WorkFLowWeaveError, match="Plaintext"):
        transform_annotations({"secret": "private"}, schema, normalize)
    original = {"path": "out.txt", "secret": {"kind": "env", "name": "TOKEN"}}
    frozen_schema, frozen_original = deepcopy(schema), deepcopy(original)
    result = transform_annotations(original, schema, normalize)
    assert result == {**original, "path": "/data/out.txt"}
    assert schema == frozen_schema and original == frozen_original


@pytest.mark.parametrize("keyword", ["anyOf", "oneOf"])
def test_only_matching_branches_apply_and_matching_uses_original_value(keyword):
    schema = {
        "type": "object", "properties": {
            "value": {keyword: [
                {"type": "string", "pattern": "^relative", "x-workflowweave-path": True},
                {"type": "integer", "x-workflowweave-credential": True},
            ]},
        },
    }
    assert transform_annotations({"value": "relative.txt"}, schema, normalize) == {
        "value": "/data/relative.txt"}
    assert transform_annotations({"value": 3}, schema, normalize) == {"value": 3}


def test_allof_and_recursive_refs_visit_nested_objects_and_arrays():
    schema = {
        "type": "object", "$defs": {
            "node": {
                "type": "object", "properties": {
                    "path": {"allOf": [{"type": "string", "x-workflowweave-path": True}]},
                    "children": {"type": "array", "items": {"$ref": "#/$defs/node"}},
                },
            },
        },
        "properties": {"root": {"$ref": "#/$defs/node"}},
    }
    data = {"root": {"path": "a", "children": [{"path": "b", "children": []}]}}
    assert transform_annotations(data, schema, normalize) == {
        "root": {"path": "/data/a", "children": [{"path": "/data/b", "children": []}]}}


def test_unknown_properties_remain_for_normal_validation():
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    result = transform_annotations({"unknown": "value"}, schema, normalize)
    assert result == {"unknown": "value"}
    with pytest.raises(WorkFLowWeaveError):
        validate_instance(result, schema)


def test_pattern_properties_additional_properties_and_tuple_items():
    path = {"type": "string", "x-workflowweave-path": True}
    schema = {"type": "object", "properties": {
        "paths": {"type": "object", "patternProperties": {"^p": path},
                  "additionalProperties": path},
        "tuple": {"type": "array", "prefixItems": [path], "items": path},
    }}
    assert transform_annotations({"paths": {"p": "a", "other": "b"}, "tuple": ["c", "d"]},
                                 schema, normalize) == {
        "paths": {"p": "/data/a", "other": "/data/b"}, "tuple": ["/data/c", "/data/d"]}


def test_referenced_condition_uses_correct_local_resolver():
    schema = {"type": "object", "$defs": {
        "kind": {"type": "string", "const": "file"},
        "file": {"type": "object", "properties": {"kind": {"$ref": "#/$defs/kind"}}},
    }, "if": {"$ref": "#/$defs/file"}, "then": {
        "properties": {"path": {"type": "string", "x-workflowweave-path": True}},
    }}
    assert transform_annotations({"kind": "file", "path": "x"}, schema, normalize)["path"] == "/data/x"
    assert transform_annotations({"kind": "text", "path": "x"}, schema, normalize)["path"] == "x"


def test_duplicate_refs_transform_each_value_once():
    schema = {"type": "object", "$defs": {"value": {"type": "string", "suffix": True}},
              "properties": {"value": {"allOf": [
                  {"$ref": "#/$defs/value"}, {"$ref": "#/$defs/value"}]}}}
    result = transform_annotations({"value": "x"}, schema,
                                   lambda value, rule: value + "!" if rule.get("suffix") else value)
    assert result == {"value": "x!"}
