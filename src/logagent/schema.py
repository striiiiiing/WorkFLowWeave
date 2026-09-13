"""JSON Schema 2020-12 validation shared by discovery and collection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, SchemaError, validators
from pydantic import TypeAdapter, ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from logagent.errors import LogAgentError, validation_error
from logagent.models import JSONObject

_JSON_OBJECT = TypeAdapter(JSONObject)


def _schema_graph(value: dict[str, Any]) -> tuple[dict[int, Any], dict[int, list[int]]]:
    """Resolve every actual schema reference without traversing annotation data.

    Registry's default retriever refuses external I/O. Its resource traversal
    and resolver handle JSON pointers, anchors and nested $id scopes together.
    """
    root = DRAFT202012.create_resource(value)
    registry = Registry().with_resource(root.id() or "", root).crawl()
    nodes: dict[int, Any] = {}
    resolvers: dict[int, Any] = {}
    references: dict[int, list[int]] = {}
    pending: list[int] = []

    def add(resource: Resource[Any], resolver: Any) -> None:
        stack = [(resource, resolver)]
        while stack:
            current, scope = stack.pop()
            key = id(current.contents)
            if key in nodes:
                continue
            nodes[key] = current.contents
            resolvers[key] = scope
            references[key] = []
            pending.append(key)
            # Defaults, examples, const and enum values are never subresources.
            for child in current.subresources():
                stack.append((child, scope.in_subresource(child)))

    add(root, registry.resolver(root.id() or ""))
    for key in pending:
        node = nodes[key]
        if not isinstance(node, dict):
            continue
        for keyword in ("$ref", "$dynamicRef"):
            if keyword not in node:
                continue
            reference = node[keyword]
            if not reference.startswith("#"):
                raise LogAgentError("invalid_schema", "schema 引用必须在同一声明内解析")
            try:
                resolved = resolvers[key].lookup(reference)
            except Exception as exc:
                raise LogAgentError(
                    "invalid_schema",
                    "schema 局部引用无法解析",
                    {"exception_type": type(exc).__name__},
                ) from None
            if not isinstance(resolved.contents, dict | bool):
                raise LogAgentError("invalid_schema", "schema 引用的目标必须为对象或布尔 schema")
            target = id(resolved.contents)
            if target not in nodes:
                # Explicit references may target a schema stored outside a
                # standard subschema keyword; validate that target as a schema.
                Draft202012Validator.check_schema(resolved.contents)
                resource = Resource.from_contents(
                    resolved.contents, default_specification=DRAFT202012
                )
                add(resource, resolved.resolver)
            references[key].append(target)
    return nodes, references


def _typed_nodes(nodes: dict[int, Any], references: dict[int, list[int]]) -> set[int]:
    """Find explicit type support, allowing grounded recursive declarations.

    A recursive candidate must be supported by actual type declarations, and
    every alternative must remain typed. Repeat both checks so a self-reference
    cannot hide an untyped alternative containing an unrelated type keyword.
    """
    conjunctions: dict[int, list[int]] = {}
    alternatives: dict[int, list[list[int]]] = {}
    dependencies: dict[int, list[int]] = {}
    explicit = set()
    for key, node in nodes.items():
        conjunctions[key] = list(references[key])
        alternatives[key] = []
        if isinstance(node, dict):
            if "type" in node:
                explicit.add(key)
            conjunctions[key].extend(id(child) for child in node.get("allOf", []))
            alternatives[key] = [
                [id(child) for child in node[word]] for word in ("anyOf", "oneOf") if word in node
            ]
        dependencies[key] = [
            *conjunctions[key],
            *(child for group in alternatives[key] for child in group),
        ]

    # A literal false schema, including aliases to it, is not a valid
    # alternative and need not provide a type for an impossible value.
    impossible = {key for key, node in nodes.items() if node is False}
    while True:
        expanded = impossible | {
            key
            for key in nodes
            if any(child in impossible for child in conjunctions[key])
            or any(
                group and all(child in impossible for child in group) for group in alternatives[key]
            )
        }
        if expanded == impossible:
            break
        impossible = expanded
    alternatives = {
        key: [[child for child in group if child not in impossible] for group in groups]
        for key, groups in alternatives.items()
    }

    supported = set(nodes)
    while True:
        while True:
            narrowed = {
                key
                for key in supported
                if key in explicit
                or any(child in supported for child in conjunctions[key])
                or any(
                    group and all(child in supported for child in group)
                    for group in alternatives[key]
                )
            }
            if narrowed == supported:
                break
            supported = narrowed

        grounded = set(explicit)
        while True:
            expanded = grounded | {
                key
                for key in supported
                if any(child in grounded for child in conjunctions[key])
                or any(
                    group
                    and all(child in supported for child in group)
                    and any(child in grounded for child in group)
                    for group in alternatives[key]
                )
            }
            if expanded == grounded:
                break
            grounded = expanded
        narrowed = supported & grounded
        if narrowed == supported:
            break
        supported = narrowed

    # References that only return to one another cannot become usable by
    # repeating validation. Reject them even when hidden in an unused $defs.
    visited: set[int] = set()
    active: set[int] = set()

    def reject_untyped_cycle(key: int) -> None:
        if key in supported or key in visited:
            return
        if key in active:
            raise LogAgentError("invalid_schema", "schema 递归引用必须包含实际类型约束")
        active.add(key)
        for child in dependencies[key]:
            reject_untyped_cycle(child)
        active.remove(key)
        visited.add(key)

    for key in nodes:
        reject_untyped_cycle(key)

    return supported


def validate_schema(schema: dict[str, Any]) -> None:
    try:
        value = _JSON_OBJECT.validate_python(schema)
        Draft202012Validator.check_schema(value)
    except ValidationError as exc:
        raise validation_error(exc, code="invalid_schema") from None
    except (SchemaError, RecursionError):
        raise LogAgentError("invalid_schema", "JSON Schema 2020-12 声明无效") from None
    if value.get("type") != "object":
        raise LogAgentError("invalid_schema", "能力 schema 的根类型必须为 object")
    if "$schema" in value and value["$schema"].rstrip("#") != (
        "https://json-schema.org/draft/2020-12/schema"
    ):
        raise LogAgentError("invalid_schema", "能力 schema 必须使用 JSON Schema 2020-12")
    try:
        nodes, references = _schema_graph(value)
        typed = _typed_nodes(nodes, references)
    except LogAgentError:
        raise
    except Exception as exc:
        raise LogAgentError(
            "invalid_schema", "schema 声明无法完成本地校验", {"exception_type": type(exc).__name__}
        ) from None
    for name, rule in value.get("properties", {}).items():
        if (
            not isinstance(rule, dict)
            or not isinstance(rule.get("description"), str)
            or not rule["description"].strip()
            or id(rule) not in typed
        ):
            raise LogAgentError(
                "invalid_schema", "每个可配置字段必须声明类型及说明", {"field": name}
            )


def validate_instance(
    instance: dict[str, Any],
    schema: dict[str, Any],
    *,
    path: list[str | int] | None = None,
    partial: bool = False,
) -> None:
    """Validate without mutating data, exposing values, or fetching remote refs."""
    try:
        value = _JSON_OBJECT.validate_python(instance)
    except ValidationError as exc:
        raise validation_error(exc) from None
    validator_class = Draft202012Validator
    if partial:
        # Skip requirements only on the object being filled by the instance.
        # Identity also handles local refs/allOf without relaxing nested values,
        # whose keys will be replaced as a unit under shallow merging.
        def partial_required(validator: Any, required: Any, current: Any, rules: Any):
            if current is not value:
                yield from Draft202012Validator.VALIDATORS["required"](
                    validator, required, current, rules
                )

        validator_class = validators.extend(Draft202012Validator, {"required": partial_required})
    try:
        errors = list(
            validator_class(
                schema, format_checker=FormatChecker(), registry=Registry()
            ).iter_errors(value)
        )
    except Exception as exc:
        raise LogAgentError(
            "invalid_schema", "schema 无法完成本地校验", {"exception_type": type(exc).__name__}
        ) from None
    if errors:
        issues = [
            {"path": [*(path or []), *error.absolute_path], "reason": str(error.validator)}
            for error in errors
        ]
        raise LogAgentError("invalid_config", "配置不符合能力 schema", {"errors": issues})


def schema_defaults(schema: dict[str, Any]) -> dict[str, Any]:
    """Only explicitly declared top-level defaults participate in shallow merge."""
    return {
        name: deepcopy(rule["default"])
        for name, rule in schema.get("properties", {}).items()
        if isinstance(rule, dict) and "default" in rule
    }
