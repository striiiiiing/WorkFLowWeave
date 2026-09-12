"""An offline source with explicitly configured, independent JSON records."""

from copy import deepcopy
from typing import Any

from pydantic import Field, field_validator

from logagent.models import Model, validate_json_value

from .base import BaseCollector, CollectionContext
from .setters import CommonSetters


class MockOptions(Model):
    items: list[dict[str, Any]] = Field(default_factory=list)

    _json = field_validator("items", mode="before")(validate_json_value)


class MockCollector(BaseCollector):
    name = "mock"
    description = "Collect independent records from configured JSON data."
    options_model = MockOptions
    setters_model = CommonSetters
    fields = ()

    def fields_for(self, options: MockOptions) -> tuple[str, ...]:
        return tuple(dict.fromkeys(key for item in options.items for key in item))

    async def collect(
        self, options: MockOptions, setters: CommonSetters, context: CollectionContext
    ) -> list[dict]:
        return deepcopy(options.items)
