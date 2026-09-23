"""Published capability views never expose mutable declaration state."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pydantic import ValidationError

from logagent.errors import LogAgentError, validation_error
from logagent.models import CapabilityDescription, ErrorInfo, JSONObject
from logagent.protocols import ChannelType, Collector, Tool
from logagent.schema import schema_defaults, validate_instance, validate_schema


def _check_callable(function: Any, arguments: int, *, asynchronous: bool) -> None:
    if not callable(function) or inspect.iscoroutinefunction(function) != asynchronous:
        raise LogAgentError("invalid_declaration", "能力实现的同步或异步调用形式不符合契约")
    try:
        inspect.signature(function).bind(*([None] * arguments))
    except (TypeError, ValueError):
        raise LogAgentError("invalid_declaration", "能力实现的参数不符合调用契约") from None


def _check_description(description: CapabilityDescription) -> None:
    if not description.description.strip():
        raise LogAgentError("invalid_declaration", "能力说明不能为空白")
    if len(description.fields) != len(set(description.fields)) or any(
        not field.strip() for field in description.fields
    ):
        raise LogAgentError("invalid_declaration", "能力字段必须非空且不重复")
    validate_schema(description.options_schema)
    validate_instance(
        schema_defaults(description.options_schema), description.options_schema, partial=True
    )
    if description.setters_schema is not None:
        validate_schema(description.setters_schema)


@dataclass(frozen=True, slots=True)
class _CollectorRegistration:
    description: CapabilityDescription
    implementation: Callable[..., Any]
    validator: Callable[..., Any] | None = None


@dataclass(frozen=True, slots=True)
class _ChannelRegistration:
    description: CapabilityDescription
    implementation: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class _ToolRegistration:
    description: CapabilityDescription
    implementation: Callable[..., Any]


def collector_registration(collector: Collector, owner: str) -> _CollectorRegistration:
    """Capture the implementation once, independently of later attribute changes."""
    implementation = collector.collect
    _check_callable(implementation, 3, asynchronous=True)
    validator = getattr(collector, "validate", None)
    if validator is not None:
        _check_callable(validator, 2, asynchronous=False)
    try:
        description = CapabilityDescription(
            kind="collector",
            name=collector.name,
            id_prefix=getattr(collector, "id_prefix", None),
            description=collector.description,
            plugin=owner,
            capabilities=["collection"],
            options_schema=deepcopy(collector.options_schema),
            setters_schema=deepcopy(collector.setters_schema),
            fields=deepcopy(getattr(collector, "fields", [])),
            count_unit=collector.count_unit,
            execution=getattr(collector, "execution", "exclusive"),
        )
    except ValidationError as exc:
        raise validation_error(exc, code="invalid_declaration") from None
    if not description.count_unit or not description.count_unit.strip():
        # 我确实很喜欢计数单位，我觉得他们会让模型有所提升，虽然我没证据
        raise LogAgentError("invalid_declaration", "Collector 必须声明非空计数单位")
    _check_description(description)
    return _CollectorRegistration(description, implementation, validator)


def channel_registration(channel: ChannelType, owner: str) -> _ChannelRegistration:
    implementation = channel.create
    _check_callable(implementation, 2, asynchronous=True)
    try:
        description = CapabilityDescription(
            kind="channel",
            name=channel.name,
            id_prefix=getattr(channel, "id_prefix", None),
            description=channel.description,
            plugin=owner,
            capabilities=deepcopy(channel.capabilities),
            options_schema=deepcopy(channel.options_schema),
        )
    except ValidationError as exc:
        raise validation_error(exc, code="invalid_declaration") from None
    _check_description(description)
    return _ChannelRegistration(description, implementation)


def tool_registration(tool: Tool, owner: str) -> _ToolRegistration:
    implementation = tool.invoke
    _check_callable(implementation, 2, asynchronous=True)
    try:
        description = CapabilityDescription(
            kind="tool", name=tool.name, description=tool.description, plugin=owner,
            capabilities=["tool"], options_schema={"type": "object", "properties": {}},
            input_schema=deepcopy(tool.input_schema), execution=tool.execution,
        )
    except ValidationError as exc:
        raise validation_error(exc, code="invalid_declaration") from None
    _check_description(description)
    validate_schema(description.input_schema)
    return _ToolRegistration(description, implementation)


@dataclass(frozen=True, slots=True)
class _RegisteredTool:
    _registration: _ToolRegistration

    @property
    def name(self):
        return self._registration.description.name

    @property
    def description(self):
        return self._registration.description.description

    @property
    def input_schema(self):
        return deepcopy(self._registration.description.input_schema)

    @property
    def execution(self):
        return self._registration.description.execution

    @property
    def invoke(self):
        return self._registration.implementation


@dataclass(frozen=True, slots=True)
class _RegisteredCollector:
    _registration: _CollectorRegistration

    @property
    def name(self) -> str:
        return self._registration.description.name

    @property
    def description(self) -> str:
        return self._registration.description.description

    @property
    def fields(self) -> list[str]:
        return list(self._registration.description.fields)

    @property
    def count_unit(self) -> str:
        return self._registration.description.count_unit or ""

    @property
    def options_schema(self) -> JSONObject:
        return deepcopy(self._registration.description.options_schema)

    @property
    def setters_schema(self) -> JSONObject:
        return deepcopy(self._registration.description.setters_schema or {})

    @property
    def collect(self) -> Callable[..., Any]:
        return self._registration.implementation

    @property
    def validate(self) -> Callable[..., Any] | None:
        validator = self._registration.validator
        if validator is None:
            return None

        def validate(options: JSONObject, setters: JSONObject) -> None:
            result = validator(deepcopy(options), deepcopy(setters))
            if inspect.iscoroutine(result):
                result.close()
            if result is not None:
                raise LogAgentError("invalid_config", "Collector.validate 必须同步返回 None")

        return validate


@dataclass(frozen=True, slots=True)
class _RegisteredChannel:
    _registration: _ChannelRegistration

    @property
    def name(self) -> str:
        return self._registration.description.name

    @property
    def description(self) -> str:
        return self._registration.description.description

    @property
    def capabilities(self) -> list[str]:
        return list(self._registration.description.capabilities)

    @property
    def options_schema(self) -> JSONObject:
        return deepcopy(self._registration.description.options_schema)

    @property
    def create(self) -> Callable[..., Any]:
        return self._registration.implementation


class _RegisterView:
    """Private storage is copied at publication; all public data reads are copies."""

    __slots__ = ("_errors", "_registrations")

    def __init__(
        self,
        registrations: Mapping[
            str, _CollectorRegistration | _ChannelRegistration | _ToolRegistration
        ] | None = None,
        *,
        errors: Iterable[ErrorInfo] = (),
    ) -> None:
        self._registrations = MappingProxyType(dict(registrations or {}))
        self._errors = tuple(error.model_copy(deep=True) for error in errors)

    def describe(self) -> list[CapabilityDescription]:
        return [
            registration.description.model_copy(deep=True)
            for registration in self._registrations.values()
        ]

    def diagnostics(self, name: str) -> list[ErrorInfo]:
        return [
            error.model_copy(deep=True)
            for error in self._errors
            if not error.details.get("capabilities")
            or name in error.details["capabilities"]
            or error.details.get("plugin") == name
        ]


class CollectorRegister(_RegisterView):
    """Read-only CollectorRegistryView published by the configuration module."""

    __slots__ = ()

    def get(self, name: str) -> Collector | None:
        registration = self._registrations.get(name)
        if registration is None:
            return None
        return _RegisteredCollector(
            _CollectorRegistration(
                registration.description.model_copy(deep=True),
                registration.implementation,
                registration.validator,
            )
        )


class ChannelRegister(_RegisterView):
    __slots__ = ()

    def get(self, name: str) -> ChannelType | None:
        registration = self._registrations.get(name)
        if registration is None:
            return None
        return _RegisteredChannel(
            _ChannelRegistration(
                registration.description.model_copy(deep=True), registration.implementation
            )
        )


class ToolRegister(_RegisterView):
    __slots__ = ("_plugins",)

    def __init__(self, registrations=None, *, errors=(), plugins=()):
        super().__init__(registrations, errors=errors)
        self._plugins = tuple(deepcopy(item) for item in plugins)

    def plugins(self):
        """Discovery metadata, including disabled entries without importing them."""
        return deepcopy(list(self._plugins))

    def get(self, name: str) -> Tool | None:
        registration = self._registrations.get(name)
        if registration is None:
            return None
        return _RegisteredTool(_ToolRegistration(
            registration.description.model_copy(deep=True), registration.implementation,
        ))
