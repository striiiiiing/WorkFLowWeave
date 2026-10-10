"""Evaluate real format budgets, retry accounting and judge result validation."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.dataset import public_cases
from evals.inputs import CONDITIONS, prepare
from evals.report import paired_results, retained_rows
from evals.run_eval import DIMENSIONS, validate_judgment
from evals.business import ROUTES, calculate_total_cost, validate_routes
from workflowweave.workflow.input_formats import equal_json, serialize


def test_public_dataset_corruption_is_rejected():
    with pytest.raises(ValueError, match="SHA-256"):
        public_cases(b"different data")


def test_zon_preserves_repeated_values_with_trailing_whitespace():
    import zon
    rows = [{"id": index, "message": "repeated diagnostic text " * 20} for index in range(6)]
    assert equal_json(rows, zon.decode(serialize(rows, "zon")))


def test_public_sample_has_small_labeled_error_and_recent_windows():
    data = (Path(__file__).parents[1] / "evals/data/kaggle-security-logs-sample.json").read_bytes()
    cases = public_cases(data)
    assert {case["id"] for case in cases} == {"cloudtrail-accessdenied", "okta-auth-outcomes"}
    for case in cases:
        assert len(case["sources"]["errors"]) == 100
        assert len(case["sources"]["recent"]) == 100
        assert case["reference"]["selected_records"] == 200


@pytest.mark.parametrize("condition", CONDITIONS)
def test_actual_production_formats_enforce_budget_and_order(condition):
    data = (Path(__file__).parents[1] / "evals/data/kaggle-security-logs-sample.json").read_bytes()
    case = public_cases(data)[0]
    result = prepare(case, condition)
    assert result["text"].startswith("[source=errors;")
    assert [v["source_id"] for v in result["views"]] == ["errors", "recent"]
    assert result["characters"] > 0
    assert not any(v["truncated"] for v in result["views"])
    if condition.endswith("summary") or condition.endswith("summary_filtered"):
        assert result["workflow"]["fan_in"]["single_task_optimization"] is False
        assert result["workflow"]["fan_in"]["order"] == ["compress"]
        assert "$input" not in result["workflow"]["fan_in"]["order"]


def test_judge_rejects_boolean_score_and_unknown_winner():
    valid = {"winner": "A", "scores": {label: dict.fromkeys(DIMENSIONS, 4) for label in ("A", "B")}}
    assert validate_judgment(valid) == valid
    boolean = copy.deepcopy(valid)
    boolean["scores"]["A"][DIMENSIONS[0]] = True
    with pytest.raises(ValueError, match="score"):
        validate_judgment(boolean)
    with pytest.raises(ValueError, match="winner"):
        validate_judgment({**valid, "winner": "other"})


def test_pairwise_winner_is_mapped_after_position_swap_and_conflicts_disclosed():
    ab = {"status": "success", "case": "c", "labels": {"A": "json_full", "B": "zon_filtered"}, "judgment": {"winner": "B"}}
    ba = {"status": "success", "case": "c", "labels": {"A": "zon_filtered", "B": "json_full"}, "judgment": {"winner": "A"}}
    assert paired_results([ab, ba])[0]["winner"] == "zon_filtered"
    conflicting = {**ba, "judgment": {"winner": "B"}}
    pair = paired_results([ab, conflicting])[0]
    assert pair["position_conflict"] and pair["winner"] is None


def test_retained_row_metric_does_not_count_partial_record_as_complete():
    case = {"sources": {"errors": [{"id": 1, "description": "first"}, {"id": 2, "description": "second"}]}}
    item = {"condition": "json_full", "views": [{"source_id": "errors", "omitted": False,
             "text": '[source=errors; incomplete]\n[{"id":1,"description":"first"},{"id":2}]'}]}
    assert retained_rows(item, case) == {"errors": {"retained": 1, "original": 2}}


async def test_judge_only_reuses_business_outputs_without_calling_business_models(tmp_path, monkeypatch):
    from evals import run_eval
    source = tmp_path / "source"
    source.mkdir()
    case = {"id": "saved", "provenance": "authored_synthetic", "task": "inspect", "reference": {}}
    candidates = [{"case": "saved", "condition": c, "status": "success", "text": "saved report"} for c in CONDITIONS]
    for name, value in (("cases.json", [case]), ("candidates.json", candidates), ("dataset.json", {})):
        (source / name).write_text(json.dumps(value))
    (source / "LOGHUB-LICENSE.txt").write_text("notice")
    (source / "inputs.jsonl").write_text("")
    (source / "requests.jsonl").write_text('{"call_id":"saved/json_full/analysis","response_id":"existing"}\n')
    orientations = []

    async def forbidden(*args):
        raise AssertionError("business model must not be called again")

    async def fake_judge(_client, _semaphore, _args, _output, _case, _baseline, other, reverse):
        orientations.append((other["condition"], reverse))
        return {"status": "success"}

    monkeypatch.setattr(run_eval, "candidate", forbidden)
    monkeypatch.setattr(run_eval, "judge", fake_judge)
    output = tmp_path / "new"
    await run_eval.run(SimpleNamespace(output=output, judge_only=source, ignore_proxy_env=True,
                       prepare_only=False, api_key="test", base_url="http://127.0.0.1:1/v1",
                       concurrency=1, judge_interval=0))
    assert len(orientations) == (len(CONDITIONS) - 1) * 2
    assert [json.loads(line) for line in (output / "requests.jsonl").read_text().splitlines()] == [
        json.loads(line) for line in (source / "requests.jsonl").read_text().splitlines()
    ]
    assert json.loads((output / "run.json").read_text())["business_reused_from"] == str(source)


def test_business_routes_fix_luna_to_sol_and_only_change_compression_prompt():
    validate_routes()
    original, generic, custom = ROUTES
    assert original.compressor_model is None
    assert {generic.compressor_model, custom.compressor_model} == {"gpt-6-luna"}
    assert {route.analyzer_model for route in ROUTES} == {"gpt-6.1-sol"}
    assert generic.analysis_prompt == custom.analysis_prompt == original.analysis_prompt
    assert generic.compression_prompt_hash != custom.compression_prompt_hash


def test_business_routes_reject_downstream_or_model_drift():
    original, generic, custom = ROUTES
    with pytest.raises(ValueError, match="analysis configuration"):
        validate_routes((original, generic, custom.__class__(**{**custom.__dict__, "analysis_prompt": "changed"})))
    with pytest.raises(ValueError, match="compression model"):
        validate_routes((original, generic.__class__(**{**generic.__dict__, "compressor_model": "gpt-4o"}), custom))


def test_cost_accounting_marks_missing_usage_and_does_not_call_it_free():
    result = calculate_total_cost([
        {"call_id": "compress", "status": "resolved", "usage": [{"total_cost": "0.01"}]},
        {"call_id": "analysis", "status": "ledger_usage_missing", "usage": []},
    ])
    assert result["observed_usd"] == pytest.approx(0.01)
    assert result["total_usd"] is None
    assert result["missing"] == ["analysis"]


def test_longmemeval_shuffle_reserves_first_hundred(tmp_path):
    from evals.run_longmemeval import select_entries, shuffled_entries
    path = tmp_path / "data.json"
    path.write_text(json.dumps([{"question_id": str(i)} for i in range(1, 501)]))
    shuffled = shuffled_entries(path, 7)
    pilot = select_entries(path, 101, 110, 7)
    assert [item["question_id"] for item in pilot] == [item["question_id"] for item in shuffled[100:110]]
    with pytest.raises(ValueError, match="reserved first 100"):
        select_entries(path, 100, 100, 7)
