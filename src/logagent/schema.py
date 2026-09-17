"""Small, local JSON Schema helpers shared by plugin discovery and collection."""

from __future__ import annotations

import re
from collections.abc import Callable
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
        self.resolvers: dict[int, Any] = {}
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
        self.resolvers[id(node)] = resolver
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

    def remove_root_requirements(
        self, schema: dict[str, Any], names: set[str] | None = None
    ) -> None:
        seen: set[int] = set()

        def visit(node: Any) -> None:
            if not isinstance(node, dict) or id(node) in seen:
                return
            seen.add(id(node))
            if names is None:
                node.pop("required", None)
            elif "required" in node:
                node["required"] = [name for name in node["required"] if name not in names]
            for target in self.references.get(id(node), []):
                visit(target)
            for keyword in ("allOf", "anyOf", "oneOf"):
                for child in node.get(keyword, []):
                    visit(child)
            if names is not None:
                for keyword in ("then", "else"):
                    visit(node.get(keyword))
                for child in node.get("dependentSchemas", {}).values():
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
        graph = _SchemaGraph(value)
        graph.check_field_types(value)
        for rule in value.get("properties", {}).values():
            if not isinstance(rule, dict):
                continue
            marker = rule.get("x-logagent-workflow", False)
            if type(marker) is not bool:
                raise _invalid_schema("x-logagent-workflow 必须为布尔值")
            if marker and _contains_credential(rule, graph):
                raise _invalid_schema("凭据只能配置在实例层")
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


def transform_annotations(
    instance: Any, schema: dict[str, Any], transform: Callable[[Any, dict[str, Any]], Any]
) -> Any:
    """Transform declared values through local references and applicable schemas.

    Branch selection uses the original value, before transformations such as
    path resolution. Structural validation remains the caller's responsibility;
    unknown properties are retained so validation can reject them normally.
    """
    graph = _SchemaGraph(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker(), registry=graph.registry)
    visited: set[tuple[tuple[str | int, ...], int]] = set()

    def matches(value: Any, rule: Any) -> bool:
        return not any(validator.descend(value, rule, resolver=graph.resolvers[id(rule)]))

    def visit(value: Any, original: Any, rule: Any, path: tuple[str | int, ...]) -> Any:
        if not isinstance(rule, dict) or (path, id(rule)) in visited:
            return value
        visited.add((path, id(rule)))
        applicable = list(graph.references.get(id(rule), []))
        applicable.extend(rule.get("allOf", []))
        for keyword in ("anyOf", "oneOf"):
            applicable.extend(branch for branch in rule.get(keyword, []) if matches(original, branch))
        if "if" in rule:
            branch = "then" if matches(original, rule["if"]) else "else"
            if branch in rule:
                applicable.append(rule[branch])
        if isinstance(original, dict):
            applicable.extend(branch for key, branch in rule.get("dependentSchemas", {}).items()
                              if key in original)
        value = transform(value, rule)
        for branch in applicable:
            value = visit(value, original, branch, path)
        if isinstance(value, dict) and isinstance(original, dict):
            properties = rule.get("properties", {})
            patterns = rule.get("patternProperties", {})
            result = {}
            for key, item in value.items():
                declarations = [properties[key]] if key in properties else []
                declarations.extend(child for pattern, child in patterns.items() if re.search(pattern, key))
                if not declarations and "additionalProperties" in rule:
                    declarations.append(rule["additionalProperties"])
                for child in declarations:
                    item = visit(item, original.get(key, item), child, (*path, key))
                result[key] = item
            return result
        if isinstance(value, list) and isinstance(original, list):
            prefix = rule.get("prefixItems", [])
            return [visit(item, original[index], prefix[index] if index < len(prefix)
                          else rule.get("items"), (*path, index))
                    for index, item in enumerate(value)]
        return value

    try:
        return visit(deepcopy(instance), instance, schema, ())
    except RecursionError:
        raise _invalid_schema("JSON Schema 或实例嵌套层级过深") from None


def _contains_credential(rule: Any, graph: _SchemaGraph) -> bool:
    seen = set()

    def visit(node):
        if not isinstance(node, dict) or id(node) in seen:
            return False
        seen.add(id(node))
        if node.get("x-logagent-credential") is True:
            return True
        if any(visit(target) for target in graph.references.get(id(node), [])):
            return True
        return any(visit(child.contents)
                   for child in DRAFT202012.create_resource(node).subresources())

    return visit(rule)


def workflow_option_names(schema: dict[str, Any]) -> set[str]:
    """Only explicit top-level declarations expose per-workflow options."""
    return {name for name, rule in schema.get("properties", {}).items()
            if isinstance(rule, dict) and rule.get("x-logagent-workflow") is True}


def split_options(options: JSONObject, schema: dict[str, Any]) -> tuple[JSONObject, JSONObject]:
    names = workflow_option_names(schema)
    return (
        {key: deepcopy(value) for key, value in options.items() if key not in names},
        {key: deepcopy(value) for key, value in options.items() if key in names},
    )


def options_complete(options: JSONObject, schema: dict[str, Any]) -> bool:
    """Whether a resource is ready for call-level semantic validation."""
    graph = _SchemaGraph(schema)
    return Draft202012Validator(
        schema, format_checker=FormatChecker(), registry=graph.registry
    ).is_valid(options)


def resource_options_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Defer required call options until workflow binding; keep account requirements."""
    result = deepcopy(schema)
    _SchemaGraph(result).remove_root_requirements(result, workflow_option_names(schema))
    return result


def validate_workflow_options(options: JSONObject, schema: dict[str, Any]) -> None:
    unknown = options.keys() - workflow_option_names(schema)
    if unknown:
        raise LogAgentError("invalid_config", "Workflow 只能设置声明的调用选项",
                            {"errors": [{"path": ["options", name], "reason": "instance_only"}
                                        for name in sorted(unknown)]})
    # Full constraints are checked against the merged effective configuration.
