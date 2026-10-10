"""Published capability views never expose mutable declaration state."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pydantic import ValidationError

from workflowweave.errors import WorkFLowWeaveError, validation_error
from workflowweave.models import CapabilityDescription, ErrorInfo, JSONObject
from workflowweave.protocols import ChannelType, Tool
from workflowweave.schema import schema_defaults, validate_instance, validate_schema


def _check_callable(function: Any, arguments: int, *, asynchronous: bool) -> None:
    if not callable(function) or inspect.iscoroutinefunction(function) != asynchronous:
        raise WorkFLowWeaveError("invalid_declaration", "能力实现的同步或异步调用形式不符合契约")
    try:
        inspect.signature(function).bind(*([None] * arguments))
    except (TypeError, ValueError):
        raise WorkFLowWeaveError("invalid_declaration", "能力实现的参数不符合调用契约") from None


def _check_description(description: CapabilityDescription) -> None:
    if not description.description.strip():
        raise WorkFLowWeaveError("invalid_declaration", "能力说明不能为空白")
    validate_schema(description.options_schema)
    validate_instance(
        schema_defaults(description.options_schema), description.options_schema, partial=True
    )


@dataclass(frozen=True, slots=True)
class _ChannelRegistration:
    description: CapabilityDescription
    implementation: Callable[..., Any]
    login: Callable[..., Any] | None = None
    connection_options: Callable[..., Any] | None = None


@dataclass(frozen=True, slots=True)
class _ToolRegistration:
    description: CapabilityDescription
    implementation: Callable[..., Any]


def channel_registration(channel: ChannelType, owner: str) -> _ChannelRegistration:
    implementation = channel.create
    _check_callable(implementation, 2, asynchronous=True)
    login = getattr(channel, "start_login", None)
    if login is not None:
        _check_callable(login, 1, asynchronous=True)
    connection_options = getattr(channel, "connection_options", None)
    if connection_options is not None:
        _check_callable(connection_options, 1, asynchronous=False)
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
    return _ChannelRegistration(description, implementation, login, connection_options)


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

    @property
    def start_login(self) -> Callable[..., Any] | None:
        return self._registration.login

    @property
    def connection_options(self) -> Callable[..., Any] | None:
        return self._registration.connection_options


class _RegisterView:
    """Private storage is copied at publication; all public data reads are copies."""

    __slots__ = ("_errors", "_registrations")

    def __init__(
        self,
        registrations: Mapping[
            str, _ChannelRegistration | _ToolRegistration
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


class ChannelRegister(_RegisterView):
    __slots__ = ()

    def get(self, name: str) -> ChannelType | None:
        registration = self._registrations.get(name)
        if registration is None:
            return None
        return _RegisteredChannel(
            _ChannelRegistration(
                registration.description.model_copy(deep=True), registration.implementation,
                registration.login,
                registration.connection_options,
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
