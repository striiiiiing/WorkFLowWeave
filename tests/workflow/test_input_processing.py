from copy import deepcopy
from datetime import UTC, datetime

import pytest

from logagent.errors import LogAgentError
from logagent.models import (
    AIConfig,
    AnalysisTask,
    CollectionResult,
    SourceConfig,
    WorkflowDefinition,
    WorkflowSnapshot,
)
from logagent.workflow.input_formats import serialize, strict_json
from logagent.workflow.input_processing import extract, process_input


def snapshot(*, format="none", item=None, field=None, total=None, sources=("first",)):
    return WorkflowSnapshot(
        workflow=WorkflowDefinition(id="wf", sources=list(sources),
            analyses=[AnalysisTask(user_prompt="analyze input", id="a", ai="ai", model="test")],
            input_processing={"format": format, "total_tokens": total}),
        sources={key: SourceConfig(id=key, call={"kind": "cli", "mode": "argv", "executable": "echo"},
                 limits={"item_tokens": item, "field_tokens": field}) for key in sources},
        ai={"ai": AIConfig(id="ai", provider="test", models={"test": {}})}, channels={}, created_at=datetime.now(UTC))


def result(text, id="first"):
    return CollectionResult(source_id=id, status="success", raw={"stdout": text, "stderr": "", "exit_code": 0})


@pytest.mark.parametrize("text", ['0', 'false', 'null', '[]', '{}', '"x"'])
def test_json_scalars_and_empty_containers_remain_content(text):
    output, views = process_input(snapshot(), [result(text)])
    assert output.endswith(text) and views[0].status == "success"


@pytest.mark.parametrize("text", ['log {"a":1}', '```json\n{}\n```', '{"a":1,"a":2}', 'NaN', '1e999'])
def test_non_json_and_invalid_json_are_preserved(text):
    output, views = process_input(snapshot(format="toon"), [result(text)])
    assert output.endswith(text) and views[0].status == "success"
    assert strict_json(text)[0] is False


def test_structured_duplicate_and_original_precedence():
    raw = {"structuredContent": {"x": False}, "content": [
        {"type": "text", "text": '{ "x" : false }'},
        {"type": "text", "text": '{"x":false}'},
        {"type": "text", "text": "explanation"}]}
    parts = extract(raw, "mcp")
    assert len(parts) == 2 and parts[0].original == '{ "x" : false }'
    assert parts[1].value == "explanation"
    raw["content"].append({"type": "image", "data": "a", "mimeType": "image/png"})
    with pytest.raises(LogAgentError, match="内容块"):
        extract(raw, "mcp")


def test_type_sensitive_dedup():
    parts = extract({"structuredContent": {"x": 0}, "content": [{"type": "text", "text": '{"x":false}'}]}, "mcp")
    assert len(parts) == 2


def test_fields_keep_raw_and_atomic_types():
    incoming = result('{"x":"abcdef", "flag":false, "zero":0}')
    before = deepcopy(incoming.raw)
    output, views = process_input(snapshot(field=5), [incoming], [len])
    assert strict_json(output.split("\n", 1)[1])[1] == {"x": "abc", "flag": False, "zero": 0}
    assert views[0].truncated and "incomplete" in output and incoming.raw == before
    _, views = process_input(snapshot(field=3), [result('false')], [len])
    assert views[0].status == "failed" and views[0].error.code == "field_budget_insufficient"


def test_multimodel_item_and_total_budget_order():
    config = snapshot(item=110, total=170, sources=("first", "second", "third"))
    incoming = [result('{"text":"' + "a" * 120 + '"}', key) for key in config.workflow.sources]
    output, views = process_input(config, incoming, [len, lambda text: len(text.encode())])
    assert len(output) <= 170 and len(output.encode()) <= 170
    assert output.startswith("[source=first")
    for view in views:
        if view.text:
            assert len(view.text) <= 110
            assert strict_json(view.text.split("\n", 1)[1])[0]
    assert views[-1].omitted and "omitted sources" in output


def test_missing_tokenizer_fails_only_with_limits():
    process_input(snapshot(), [result("abc")])
    with pytest.raises(LogAgentError, match="计量能力"):
        process_input(snapshot(item=5), [result("abc")])


@pytest.mark.parametrize("format", ["none", "ison", "toon", "zon", "md", "csv"])
def test_supported_formats_and_budget_syntax(format):
    value = [{"name": "x", "amount": 1}, {"name": "y", "amount": 2}]
    assert serialize(value, format)
    output, views = process_input(snapshot(format=format, item=160), [result(__import__('json').dumps(value))], [len])
    assert len(output) <= 160 and views[0].status == "success"


def test_format_failure_keeps_successful_acquisition_separate():
    acquired = result('{"nested":[1]}')
    output, views = process_input(snapshot(format="csv"), [acquired])
    assert acquired.status == "success" and views[0].status == "failed" and output == ""


def test_none_keeps_whitespace_and_budget_compaction_is_not_truncation():
    text = '{  "a"  :  1  }'
    output, views = process_input(snapshot(), [result(text)])
    assert output.endswith(text) and not views[0].truncated
    output, views = process_input(snapshot(item=36), [result(text)], [len])
    assert len(output) <= 36 and not views[0].truncated
