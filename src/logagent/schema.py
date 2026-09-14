"""Small, local JSON Schema helpers shared by plugin discovery and collection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, SchemaError
from pydantic import TypeAdapter, ValidationError

from logagent.errors import LogAgentError, validation_error
from logagent.models import JSONObject

_JSON_OBJECT = TypeAdapter(JSONObject)
_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def validate_schema(schema: dict[str, Any]) -> None:
    """Use the standard JSON Schema implementation; no parallel type system."""
    try:
        value = _JSON_OBJECT.validate_python(schema)
        Draft202012Validator.check_schema(value)
    except ValidationError as exc:
        raise validation_error(exc, code="invalid_schema") from None
    except (SchemaError, RecursionError):
        raise LogAgentError("invalid_schema", "JSON Schema 2020-12 声明无效") from None
    if value.get("type") != "object":
        raise LogAgentError("invalid_schema", "能力 schema 的根类型必须为 object")
    if "$schema" in value and value["$schema"].rstrip("#") != _DRAFT:
        raise LogAgentError("invalid_schema", "能力 schema 必须使用 JSON Schema 2020-12")
    for name, rule in value.get("properties", {}).items():
        if not isinstance(rule, dict) or not isinstance(rule.get("description"), str):
            raise LogAgentError("invalid_schema", "每个可配置字段必须声明类型及说明", {"field": name})


def validate_instance(instance: dict[str, Any], schema: dict[str, Any], *,
                      path: list[str | int] | None = None, partial: bool = False) -> None:
    """Validate without mutation, value disclosure, or remote reference access."""
    try:
        value = _JSON_OBJECT.validate_python(instance)
    except ValidationError as exc:
        raise validation_error(exc) from None
    if partial:
        schema = deepcopy(schema)
        if isinstance(schema, dict):
            schema.pop("required", None)
    try:
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    except Exception as exc:
        raise LogAgentError("invalid_schema", "schema 无法完成本地校验", {"exception_type": type(exc).__name__}) from None
    if errors:
        raise LogAgentError("invalid_config", "配置不符合能力 schema", {"errors": [
            {"path": [*(path or []), *error.absolute_path], "reason": str(error.validator)}
            for error in errors
        ]})


def schema_defaults(schema: dict[str, Any]) -> dict[str, Any]:
    return {name: deepcopy(rule["default"])
            for name, rule in schema.get("properties", {}).items()
            if isinstance(rule, dict) and "default" in rule}
