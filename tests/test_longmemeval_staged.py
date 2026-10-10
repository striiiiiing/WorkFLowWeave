"""Check ledger completeness and staged execution without paid model calls."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from evals import run_longmemeval_staged as staged
from evals.audit_longmemeval import match_ledger
from evals.longmemeval_prompts import prompt_fingerprints
from evals.longmemeval_reuse import reuse_completed
from evals.summarize_longmemeval import summarize


def test_reuse_preserves_failed_source_and_does_not_repeat_success(tmp_path):
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    split = {"selected": [{"question_id": "q", "shuffled_ordinal": 104}]}
    prompts = {"B": "checkpoint", "C": "business"}
    snapshot = {"workflow": {"question": "q"}, "ai": {"model": "fixed"}}
    reports = [{"question_id": "q", "line": line, "status": "completed" if line == "A" else "failed"}
               for line in "AC"]
    judgments = [{"question_id": "q", "line": "A", "status": "success", "correct": False}]
    requests = [{"call_id": f"q/A/{stage}", "status": "success", "finish_reason": "stop",
                 "response_id": stage, "started_at": stage} for stage in ("business/analysis", "judge")]
    requests.append({"call_id": "q/C/business/compress", "status": "failed"})
    for name, value in (("split.json", split), ("compression-prompts.json", prompts),
                        ("reports.json", reports), ("judgments.json", judgments),
                        ("q-A.snapshot.json", snapshot), ("q-A.result.json", {}), ("q-A.history.json", [])):
        (source / name).write_text(json.dumps(value))
    (source / "requests.jsonl").write_text("\n".join(json.dumps(r) for r in requests))
    for directory in (source, output):
        (directory / "q-A.evidence.json").write_text("same evidence")
    before = (source / "requests.jsonl").read_text()
    rows, scores, calls, provenance = reuse_completed(source, output, split, prompts, {("q", "A"): snapshot})
    assert len(rows) == len(scores) == 1 and len(calls) == 2
    assert scores[0]["correct"] is False  # Incorrect answers are valid completed routes.
    assert provenance["excluded_requests"] == requests[-1:]
    assert (source / "requests.jsonl").read_text() == before
    (output / "q-A.evidence.json").write_text("changed evidence")
    with pytest.raises(ValueError, match="evidence differs"):
        reuse_completed(source, output, split, prompts, {("q", "A"): snapshot})


def test_summary_rejects_mixed_prompt_versions(tmp_path):
    directories = [tmp_path / "old", tmp_path / "new"]
    for directory, version in zip(directories, (None, prompt_fingerprints()), strict=True):
        directory.mkdir()
        (directory / "audit.json").write_text(json.dumps({"passed": True, "compression_prompts": version}))
        (directory / "split.json").write_text(json.dumps({"holdout_ids": [], "selected": []}))
        for name in ("reports.json", "judgments.json", "axonhub-ledger.json"):
            (directory / name).write_text("[]")
        (directory / "requests.jsonl").write_text("")
    with pytest.raises(ValueError, match="prompt versions differ"):
        summarize(directories)


@pytest.mark.parametrize("ordinal,first", [(101, 102), (102, 101)])
def test_expansion_excludes_new_singleton(ordinal, first):
    baseline = {"selected": [{"shuffled_ordinal": ordinal}], "compression_prompts": prompt_fingerprints()}
    assert staged.expansion_ranges(baseline) == ((2, first, first), (5, 103, 105), (10, 106, 110))


@pytest.mark.parametrize("fingerprints", [None, {"version": "old"}])
def test_old_prompt_singleton_cannot_be_reused(fingerprints):
    baseline = {"selected": [{"shuffled_ordinal": 102}], "compression_prompts": fingerprints}
    with pytest.raises(RuntimeError, match="prompt"):
        staged.expansion_ranges(baseline)


@pytest.mark.parametrize("cost,expected", [(None, "missing"), (0, "resolved"), (0.12, "resolved")])
def test_ledger_missing_cost_is_not_free(cost, expected):
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(
            "CREATE TABLE requests(id,api_key_id,model_id,status,external_id,reasoning_effort,stream);"
            "CREATE TABLE usage_logs(request_id,total_cost,cost_items,prompt_tokens,prompt_cached_tokens,"
            "completion_tokens,completion_reasoning_tokens);"
            "CREATE TABLE request_executions(request_id,model_id,channel_id,status);"
            "INSERT INTO requests VALUES(1,11,'gpt-6-luna','completed','response','max',1);"
        )
        connection.execute("INSERT INTO usage_logs VALUES(1,?,NULL,10,0,2,0)", (cost,))
        rows = match_ledger([{"call_id": "q/A/judge", "response_id": "response"}], connection)
    assert rows[0]["cost_status"] == expected


@pytest.mark.parametrize(("failed_stage", "audit_failure"),
                         [(None, False), (2, False), (5, False), (2, True), (5, True)])
def test_expansion_is_sequential_and_stops_on_technical_failure(tmp_path, monkeypatch, failed_stage, audit_failure):
    database = tmp_path / "ledger.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE api_keys(key,name,status,deleted_at)")
        connection.execute("INSERT INTO api_keys VALUES(?,?,?,0)", ("unit-test", "PC langchain", "enabled"))
    output = tmp_path / "results"
    monkeypatch.setattr("sys.argv", ["staged", "--dataset", "data", "--order-dataset", "order",
                        "--database", str(database), "--singleton", "singleton", "--output", str(output),
                        "--base-url", "http://unit-test/v1"])
    events = []

    def audit(directory, database):
        events.append(("audit", str(directory)))
        size = {"additional-102-102": 2, "additional-103-105": 5}.get(directory.name)
        if audit_failure and size == failed_stage:
            raise RuntimeError("technical audit failed")
        return {"passed": True, "selected": [{"shuffled_ordinal": 101}],
                "compression_prompts": prompt_fingerprints()}

    def execute(command, env, check):
        start = int(command[command.index("--start") + 1])
        size = {102: 2, 103: 5, 106: 10}[start]
        events.append(("execute", size))
        assert env[staged.CREDENTIAL_ENV] == "unit-test"
        assert command[1:3] == ["-m", "evals.run_longmemeval"]
        return SimpleNamespace(returncode=1 if size == failed_stage and not audit_failure else 0)

    monkeypatch.setattr(staged, "audit", audit)
    monkeypatch.setattr(staged.subprocess, "run", execute)
    if failed_stage:
        with pytest.raises(RuntimeError if audit_failure else SystemExit):
            staged.main()
    else:
        staged.main()
    manifest = json.loads((output / "stages.json").read_text())
    assert manifest["status"] == ("failed" if failed_stage else "complete")
    executed = [value for event, value in events if event == "execute"]
    assert executed == ([2] if failed_stage == 2 else [2, 5] if failed_stage == 5 else [2, 5, 10])
    assert all(events[index - 1][0] == "audit" for index, event in enumerate(events) if event[0] == "execute")
