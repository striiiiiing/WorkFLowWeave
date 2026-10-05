"""离线 Mock 采集器的数据转换测试。

构造固定记录，验证过滤、排序、字段投影、分组和输入不变；参数化区分
原始空与处理后空，检查混合 JSON 排序、非法选项、显式失败和可取消等待。
使用真实采集器，不依赖文件或网络数据源。
"""

import asyncio
from copy import deepcopy

import pytest

from logagent.errors import LogAgentError
from logagent.models import CollectionContext
from logagent.schema import validate_schema
from plugins.mock.collector import MockCollector

CONTEXT = CollectionContext(workflow_id="workflow", session_id="session")


async def test_default_mock_is_offline_and_its_schemas_are_valid():
    collector = MockCollector()
    validate_schema(collector.options_schema)
    validate_schema(collector.setters_schema)
    output = await collector.collect({}, {}, CONTEXT)
    assert output.status == "success"
    assert output.count == 1
    assert output.items[0]["message"] == "LogAgent mock record"
    output.items[0]["message"] = "modified"
    assert (await collector.collect({}, {}, CONTEXT)).items[0]["message"] != "modified"


async def test_filter_sort_projection_group_and_input_isolation():
    collector = MockCollector()
    options = {
        "records": [
            {"id": "c", "group": "b", "value": 3, "keep": True},
            {"id": "a", "group": "a", "value": 1, "keep": True},
            {"id": "ignored", "group": "b", "value": 0, "keep": False},
            {"id": "b", "group": "b", "value": 2, "keep": True},
        ]
    }
    setters = {
        "filter": {"keep": True},
        "sort_by": "value",
        "fields": ["id", "group", "value"],
        "group_by": "group",
    }
    original = deepcopy((options, setters))
    output = await collector.collect(options, setters, CONTEXT)
    assert output.status == "success"
    assert output.count == 3
    assert [record["id"] for record in output.items] == ["a", "b", "c"]
    assert all("keep" not in record for record in output.items)
    assert output.metadata["groups"] == [{"value": "a", "count": 1}, {"value": "b", "count": 2}]
    assert (options, setters) == original
    assert "before_count" not in output.metadata
    assert "ignored" not in output.text


@pytest.mark.parametrize(
    ("options", "setters", "expected"),
    [
        ({"records": []}, {}, "empty"),
        ({"mode": "empty"}, {}, "empty"),
        ({"records": [{"a": 1}]}, {"fields": []}, "filtered_empty"),
        ({"records": [{"a": 1}]}, {"fields": ["absent"]}, "filtered_empty"),
        ({"records": [{}]}, {}, "filtered_empty"),
        ({"records": [{"a": 1}]}, {"filter": {"a": 2}}, "filtered_empty"),
        ({"records": [{"a": 1}]}, {"filter": {"a": True}}, "filtered_empty"),
        ({"records": [{"b": 1}]}, {"filter": {"a": None}}, "filtered_empty"),
    ],
)
async def test_raw_and_processed_empty_remain_distinct(options, setters, expected):
    output = await MockCollector().collect(options, setters, CONTEXT)
    assert output.status == expected
    assert output.count == 0 and output.text == "" and output.items == []


async def test_sort_handles_mixed_json_values_stably():
    records = [{"id": str(i), "a": value} for i, value in enumerate(["text", 2, None, False, 1])]
    output = await MockCollector().collect(
        {"records": records}, {"sort_by": "a", "descending": True}, CONTEXT
    )
    assert [record["a"] for record in output.items] == ["text", 2, 1, False, None]


async def test_failure_is_explicit_and_timeout_can_be_cancelled():
    failed = await MockCollector().collect({"mode": "failed"}, {}, CONTEXT)
    assert failed.status == "failed" and failed.error.code == "mock_failure"
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.02):
            await MockCollector().collect({"mode": "timeout"}, {}, CONTEXT)


@pytest.mark.parametrize(
    ("options", "setters"),
    [
        ({"records": [{}] * 1001}, {}),
        ({"mode": "typo"}, {}),
        ({}, {"unknown": True}),
        ({}, {"fields": "message"}),
        ({}, {"filter": {"message": {"nested": True}}}),
    ],
)
async def test_mock_rejects_unsupported_settings(options, setters):
    with pytest.raises(LogAgentError):
        await MockCollector().collect(options, setters, CONTEXT)
