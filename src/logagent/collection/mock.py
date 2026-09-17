"""An offline Collector with explicit failure modes and record-level Setters."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any

from logagent.models import CollectionContext, CollectorOutput, ErrorInfo, JSONObject
from logagent.schema import validate_instance

_DEFAULT_RECORDS = [
    {"id": "sample-1", "message": "LogAgent mock record", "level": "INFO", "group": "default"}
]
_MISSING = object()


def _json_equal(left: Any, right: Any) -> bool:
    if left is _MISSING:
        return False
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    return type(left) is type(right) and left == right


def _sort_key(value: Any) -> tuple[int, Any]:
    """Stable total order, including mixed JSON types and absent fields."""
    if value is _MISSING:
        return (0, "")
    if value is None:
        return (1, "")
    if type(value) is bool:
        return (2, value)
    if type(value) in (int, float):
        return (3, value)
    if isinstance(value, str):
        return (4, value)
    return (5, json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _line(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class MockCollector:
    name = "mock"
    description = "有界离线记录；支持过滤、排序、字段投影和分组，以及显式失败/超时演示。"
    fields = ["id", "message", "level", "group"]
    count_unit = "records"
    options_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "mode": {
                "x-logagent-workflow": True,
                "type": "string",
                "enum": ["success", "empty", "failed", "timeout"],
                "default": "success",
                "description": "success 处理记录；其余模式用于验证空、失败和调用方超时。",
            },
            "records": {
                "x-logagent-workflow": True,
                "type": "array",
                "maxItems": 1000,
                "items": {"type": "object"},
                "default": _DEFAULT_RECORDS,
                "description": "最多 1000 条 JSON 记录；字段可自定义，省略时使用内置样例。",
            },
        },
        "additionalProperties": False,
    }
    setters_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "description": "依次执行 filter、sort、fields、group、format；只统计处理后可消费记录。",
        "properties": {
            "fields": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 128},
                "uniqueItems": True,
                "maxItems": 128,
                "description": "按此顺序投影 records 的键；省略保留全部，空列表表示无内容。",
            },
            "filter": {
                "type": "object",
                "additionalProperties": {"type": ["string", "number", "boolean", "null"]},
                "maxProperties": 128,
                "description": "所有字段必须存在并等于给定标量；布尔值与数字不混同。",
            },
            "sort_by": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "description": "按一个字段稳定排序；缺失、null、布尔、数值、字符串、复合值依次排列。",
            },
            "descending": {
                "type": "boolean",
                "default": False,
                "description": "反向排列 sort_by 指定字段；省略时升序。",
            },
            "group_by": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "description": "投影后按一个字段分组；不存在的字段归入 null 组，计数仍按记录。",
            },
        },
        "additionalProperties": False,
    }

    async def collect(
        self, options: JSONObject, setters: JSONObject, context: CollectionContext
    ) -> CollectorOutput:
        validate_instance(options, self.options_schema, path=["options"])
        validate_instance(setters, self.setters_schema, path=["setters"])
        mode = options.get("mode", "success")
        metadata: dict[str, Any] = {
            "count_unit": self.count_unit,
            "processing_order": ["filter", "sort", "fields", "group", "format"],
        }
        if mode == "timeout":
            # Intentionally waits until its caller's deadline/cancellation. No spawned task.
            await asyncio.Future()
        if mode == "failed":
            return CollectorOutput(
                status="failed",
                error=ErrorInfo(code="mock_failure", message="Mock 来源按配置返回失败"),
                metadata=metadata,
            )
        records = deepcopy(options.get("records", _DEFAULT_RECORDS))
        if mode == "empty" or not records:
            return CollectorOutput(status="empty", metadata=metadata)

        filters = setters.get("filter", {})
        records = [
            record
            for record in records
            if all(_json_equal(record.get(key, _MISSING), value) for key, value in filters.items())
        ]
        if "sort_by" in setters:
            key = setters["sort_by"]
            records.sort(
                key=lambda record: _sort_key(record.get(key, _MISSING)),
                reverse=setters.get("descending", False),
            )
        if "fields" in setters:
            fields = setters["fields"]
            records = [{key: record[key] for key in fields if key in record} for record in records]
        records = [record for record in records if record]
        if not records:
            return CollectorOutput(status="filtered_empty", metadata=metadata)

        if "group_by" in setters:
            group_by = setters["group_by"]
            groups: dict[str, list[dict[str, Any]]] = {}
            for record in records:
                group = json.dumps(
                    record.get(group_by), ensure_ascii=False, sort_keys=True, allow_nan=False
                )
                groups.setdefault(group, []).append(record)
            text = "\n\n".join(
                f"{group_by}={group}\n" + "\n".join(_line(record) for record in values)
                for group, values in groups.items()
            )
            records = [record for group in groups.values() for record in group]
            metadata["groups"] = [
                {"value": json.loads(group), "count": len(values)}
                for group, values in groups.items()
            ]
        else:
            text = "\n".join(_line(record) for record in records)
        return CollectorOutput(
            status="success", items=records, text=text, count=len(records), metadata=metadata
        )
