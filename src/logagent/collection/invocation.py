"""Collector calls shared by Agent tools and the public HTTP/CLI boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Protocol

from pydantic import Field, ValidationError

from logagent.config.calls import normalize_call_options, resolve_source_call
from logagent.errors import LogAgentError, validation_error
from logagent.models import (
    CapabilityDescription,
    CollectionContext,
    CollectionResult,
    JSONObject,
    SourceConfig,
    SourceOverride,
    StrictModel,
)
from logagent.schema import call_options_schema


class CollectionArguments(StrictModel):
    options: JSONObject = Field(default_factory=dict)
    setters: JSONObject = Field(default_factory=dict)


class CollectionExecutor(Protocol):
    async def collect(self, source: SourceConfig, context: CollectionContext) -> CollectionResult: ...


class CollectorInvocation:
    """Use an already expanded resource snapshot and an injected single-call executor.

    Adapters capture these references synchronously before invoking; this service
    owns neither a plugin registry nor the Agent workspace scheduler.
    """

    def __init__(
        self,
        sources: Mapping[str, SourceConfig],
        descriptions: Sequence[CapabilityDescription],
        *,
        executor: CollectionExecutor,
        data_dir: Path,
    ):
        self.sources = sources
        self.descriptions = {item.name: item for item in descriptions}
        self._executor = executor
        self._data_dir = data_dir

    def target(self, ident: str) -> tuple[SourceConfig, CapabilityDescription]:
        source = self.sources.get(ident)
        if source is None or not source.enabled:
            raise LogAgentError("target_unavailable", "目标未配置或未启用")
        description = self.descriptions.get(source.collector)
        if description is None:
            raise LogAgentError("target_unavailable", "目标插件不可调用")
        return source, description

    def schema(self, ident: str) -> JSONObject:
        source, description = self.target(ident)
        options = call_options_schema(description.options_schema, source.options)
        # Each embedded schema needs its own local-reference base URI.
        options["$id"] = "urn:logagent:call-options"
        options["description"] = "Only explicit call overrides; saved values remain effective"
        setters = deepcopy(description.setters_schema)
        setters.setdefault("$id", "urn:logagent:call-setters")
        setters["description"] = "Setter overrides; omitted keys retain the saved values"
        return {
            "type": "object",
            "properties": {"options": options, "setters": setters},
            "required": ["options"] if options.get("required") else [],
            "additionalProperties": False,
        }

    async def invoke(
        self, ident: str, arguments: object, context: CollectionContext,
    ) -> CollectionResult:
        source, description = self.target(ident)
        try:
            values = CollectionArguments.model_validate(arguments)
        except ValidationError as exc:
            raise validation_error(exc, code="invalid_argument") from None
        options = normalize_call_options(
            values.options, description.options_schema, data_dir=self._data_dir,
        )
        resolved = resolve_source_call(
            source, {}, SourceOverride(options=options, setters=values.setters),
        )
        return await self._executor.collect(resolved, context)
