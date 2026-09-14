"""Small, local JSON Schema helpers shared by plugin discovery and collection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, SchemaError
from pydantic import TypeAdapter, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from logagent.errors import LogAgentError, validation_error
from logagent.models import JSONObject

_JSON_OBJECT = TypeAdapter(JSONObject)
_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _invalid_schema(message: str) -> LogAgentError:
    return LogAgentError("invalid_schema", message)


class _SchemaGraph:
    """Inspect schema locations and local references using the standard resolver.

    Annotation data is deliberately excluded by Resource.subresources(). The
    registry has no retrieval callback, so resolving can never fetch a URL.
    """

    def __init__(self, schema: dict[str, Any]) -> None:
        resource = DRAFT202012.create_resource(schema)
        base = resource.id() or ""
        self.registry = Registry().with_resource(base, resource).crawl()
        self.nodes: dict[int, Any] = {}
        self.references: dict[int, list[Any]] = {}
        self._visit(resource, self.registry.resolver(base))

    def _visit(self, resource: Any, resolver: Any) -> None:
        node = resource.contents
        if not isinstance(node, (dict, bool)):
            raise _invalid_schema("Schema 引用目标必须是 schema")
        if id(node) in self.nodes:
            return
        # A pointer may target annotation data, which check_schema(root) does
        # not validate as a schema. Check every referenced target as well.
        try:
            Draft202012Validator.check_schema(node)
        except SchemaError:
            raise _invalid_schema("JSON Schema 2020-12 声明无效") from None
        self.nodes[id(node)] = node
        if isinstance(node, bool):
            return
        for keyword in ("$ref", "$dynamicRef"):
            if keyword not in node:
                continue
            reference = node[keyword]
            if not isinstance(reference, str) or not reference.startswith("#"):
                raise _invalid_schema("Schema 只允许本地引用")
            try:
                resolved = resolver.lookup(reference)
            except (Unresolvable, ValueError, TypeError, LookupError):
                raise _invalid_schema("Schema 本地引用无法解析") from None
            self.references.setdefault(id(node), []).append(resolved.contents)
            self._visit(DRAFT202012.create_resource(resolved.contents), resolved.resolver)
        for child in resource.subresources():
            self._visit(child, resolver.in_subresource(child))

    def check_field_types(self, schema: dict[str, Any]) -> None:
        # Compute the least fixed point. A reference cycle cannot establish a
        # type merely by pointing back to itself; recursive objects can because
        # their object/array declarations provide the initial grounded nodes.
        typed = {key for key, node in self.nodes.items()
                 if node is False or isinstance(node, dict) and "type" in node}
        while True:
            before = len(typed)
            for key, node in self.nodes.items():
                if key in typed or not isinstance(node, dict):
                    continue
                if any(id(target) in typed for target in self.references.get(key, [])):
                    typed.add(key)
                elif any(id(child) in typed for child in node.get("allOf", [])):
                    typed.add(key)
                elif any(node.get(keyword) and all(id(child) in typed for child in node[keyword])
                         for keyword in ("anyOf", "oneOf")):
                    typed.add(key)
            if len(typed) == before:
                break
        if any(key not in typed for key in self.references):
            raise _invalid_schema("Schema 引用缺少可解析的类型声明")
        for rule in schema.get("properties", {}).values():
            if (not isinstance(rule, dict) or not isinstance(rule.get("description"), str)
                    or id(rule) not in typed):
                raise _invalid_schema("每个可配置字段必须声明类型及说明")

    def remove_root_requirements(self, schema: dict[str, Any]) -> None:
        seen: set[int] = set()

        def visit(node: Any) -> None:
            if not isinstance(node, dict) or id(node) in seen:
                return
            seen.add(id(node))
            node.pop("required", None)
            for target in self.references.get(id(node), []):
                visit(target)
            for keyword in ("allOf", "anyOf", "oneOf"):
                for child in node.get(keyword, []):
                    visit(child)
        visit(schema)


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
    try:
        _SchemaGraph(value).check_field_types(value)
    except RecursionError:
        raise _invalid_schema("JSON Schema 嵌套层级过深") from None


def validate_instance(instance: dict[str, Any], schema: dict[str, Any], *,
                      path: list[str | int] | None = None, partial: bool = False) -> None:
    """Validate without mutation, value disclosure, or remote reference access."""
    try:
        value = _JSON_OBJECT.validate_python(instance)
    except ValidationError as exc:
        raise validation_error(exc) from None
    try:
        if partial:
            schema = deepcopy(schema)
        graph = _SchemaGraph(schema)
        if partial:
            graph.remove_root_requirements(schema)
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker(),
                                          registry=graph.registry).iter_errors(value))
    except LogAgentError:
        raise
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
