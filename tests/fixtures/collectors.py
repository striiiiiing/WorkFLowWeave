"""Deterministic collectors for tests; never installed with WorkFLowWeave."""

from __future__ import annotations

import asyncio
from copy import deepcopy

from workflowweave.models import CollectionContext, CollectorOutput, ErrorInfo
from workflowweave.schema import validate_instance

_DEFAULT_RECORDS = [{"id": "sample-1", "message": "WorkFLowWeave mock record", "level": "INFO"}]


class MockCollector:
    name = "mock"
    execution = "read"
    id_prefix = "mock"
    description = "Deterministic test records"
    fields = ["id", "message", "level", "group"]
    count_unit = "records"
    options_schema = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["success", "empty", "failed", "timeout"],
                "default": "success",
                "description": "Test collection result mode",
                "x-workflowweave-workflow": True,
            },
            "records": {
                "type": "array",
                "items": {"type": "object"},
                "default": _DEFAULT_RECORDS,
                "description": "Records returned by this test collector",
                "x-workflowweave-workflow": True,
            },
        },
        "additionalProperties": False,
    }
    setters_schema = {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "uniqueItems": True,
                "description": "Fields retained in test records",
            },
            "filter": {
                "type": "object",
                "description": "Equality filters for test records",
                "additionalProperties": {"type": ["string", "number", "boolean", "null"]},
            },
        },
        "additionalProperties": False,
    }

    async def collect(self, options, setters, context: CollectionContext) -> CollectorOutput:
        del context
        validate_instance(options, self.options_schema, path=["options"])
        validate_instance(setters, self.setters_schema, path=["setters"])
        mode = options.get("mode", "success")
        if mode == "timeout":
            await asyncio.Future()
        if mode == "failed":
            return CollectorOutput(
                status="failed",
                error=ErrorInfo(code="test_collection_failed", message="Test collection failed"),
            )
        records = deepcopy(options.get("records", _DEFAULT_RECORDS))
        if mode == "empty" or not records:
            return CollectorOutput(status="empty")
        filters = setters.get("filter", {})
        records = [record for record in records if all(record.get(key) == value for key, value in filters.items())]
        if "fields" in setters:
            fields = setters["fields"]
            records = [{key: record[key] for key in fields if key in record} for record in records]
        records = [record for record in records if record]
        if not records:
            return CollectorOutput(status="filtered_empty")
        import json

        return CollectorOutput(
            status="success",
            items=records,
            text="\n".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in records),
            count=len(records),
            metadata={"count_unit": self.count_unit},
        )


class AlternateMockCollector(MockCollector):
    name = "alternate"


class QueryCollector(MockCollector):
    name = "query"
    options_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "host": {"type": "string", "description": "Account endpoint"},
            "path": {
                "type": "string",
                "description": "Query file",
                "x-workflowweave-workflow": True,
                "x-workflowweave-path": True,
            },
            "begin": {
                "type": "integer",
                "description": "Lower bound",
                "x-workflowweave-workflow": True,
            },
            "end": {
                "type": "integer",
                "description": "Upper bound",
                "x-workflowweave-workflow": True,
            },
        },
        "required": ["host", "path", "begin", "end"],
    }

    def validate(self, options, setters):
        del setters
        if options["begin"] > options["end"]:
            raise ValueError("Invalid query range")
