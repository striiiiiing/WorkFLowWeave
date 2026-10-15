"""Audit paid Workflow artifacts and match each response to the AxonHub ledger."""

import argparse
import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path


def read_requests(directory):
    return [json.loads(line) for line in (directory / "requests.jsonl").read_text().splitlines()]


def match_ledger(requests, connection):
    connection.row_factory = sqlite3.Row
    rows = []
    for request in requests:
        matches = connection.execute(
            "SELECT id,api_key_id,model_id,status,external_id,reasoning_effort,stream "
            "FROM requests WHERE external_id=?", (request.get("response_id"),),
        ).fetchall()
        if len(matches) != 1:
            rows.append({"call_id": request["call_id"], "cost_status": "missing"})
            continue
        row = dict(matches[0])
        row["call_id"] = request["call_id"]
        row["usage"] = []
        for usage in connection.execute(
            "SELECT total_cost,cost_items,prompt_tokens,prompt_cached_tokens,completion_tokens,"
            "completion_reasoning_tokens FROM usage_logs WHERE request_id=?", (row["id"],),
        ):
            value = dict(usage)
            value["cost_items"] = json.loads(value["cost_items"]) if value["cost_items"] else []
            row["usage"].append(value)
        row["executions"] = [dict(value) for value in connection.execute(
            "SELECT model_id,channel_id,status FROM request_executions WHERE request_id=?",
            (row["id"],),
        )]
        row["cost_status"] = "resolved" if row["usage"] and all(
            u["total_cost"] is not None for u in row["usage"]
        ) else "missing"
        rows.append(row)
    return rows


def audit_run(directory, ledger):
    import tiktoken

    run = json.loads((directory / "run.json").read_text())
    split = json.loads((directory / "split.json").read_text())
    reports = json.loads((directory / "reports.json").read_text())
    judgments = json.loads((directory / "judgments.json").read_text())
    requests = read_requests(directory)
    issues = []

    def require(condition, issue):
        if not condition:
            issues.append(issue)

    prompts = None
    if run.get("compression_prompts"):
        prompts = json.loads((directory / "compression-prompts.json").read_text())
        fingerprints = {"version": prompts["fingerprints"]["version"], **{
            line: hashlib.sha256(prompts[line].encode()).hexdigest() for line in "BC"}}
        require(fingerprints == prompts["fingerprints"] == run["compression_prompts"],
                "compression prompt manifest/hash differs")

    expected = {(entry["question_id"], line) for entry in split["selected"] for line in "ABC"}
    require(run["status"] == "complete", "run incomplete")
    require(set(split["holdout_ids"]).isdisjoint(qid for qid, _ in expected), "holdout executed")
    require({(r["question_id"], r["line"]) for r in reports} == expected
            and len(reports) == len(expected), "reports missing/duplicate")
    require({(r["question_id"], r["line"]) for r in judgments} == expected
            and len(judgments) == len(expected), "judgments missing/duplicate")
    require(all(j["status"] == "success" for j in judgments), "judge failed")
    require(len(requests) == len(expected) // 3 * 8, "request count not eight per question")
    require(len({r["call_id"] for r in requests}) == len(requests), "duplicate call IDs")
    require(len({r.get("response_id") for r in requests}) == len(requests), "duplicate response IDs")
    require(all(a["finished_at"] <= b["started_at"] for a, b in zip(requests, requests[1:], strict=False)),
            "overlapping requests")
    if issues:
        return {"passed": False, "issues": issues, "request_count": len(requests),
                "selected": split["selected"], "compression_prompts": run.get("compression_prompts")}
    by_call = {r["call_id"]: r for r in requests}
    encoding = tiktoken.get_encoding("o200k_base")
    def count(text):
        return len(encoding.encode(text, disallowed_special=()))
    for row in reports:
        qid, line = row["question_id"], row["line"]
        result = json.loads((directory / f"{qid}-{line}.result.json").read_text())
        history = json.loads((directory / f"{qid}-{line}.history.json").read_text())
        require(row["status"] == "completed" and result["status"] == "completed", f"{qid}/{line} failed")
        require(bool(history), f"{qid}/{line} history missing")
        require(bool(row["answer"].strip()), f"{qid}/{line} answer empty")
        if line != "A":
            summary = result["analyses"][0]["text"]
            require(bool(summary.strip()), f"{qid}/{line} summary empty")
            require(count(summary) <= row["text_budget"], f"{qid}/{line} compression budget exceeded")
        judge = by_call.get(f"{qid}/{line}/judge")
        require(judge is not None, f"{qid}/{line} judge request missing")
        snapshot = json.loads((directory / f"{qid}-{line}.snapshot.json").read_text())
        if line != "A" and prompts:
            require(snapshot["workflow"]["analyses"][0]["user_prompt"] == prompts[line],
                    f"{qid}/{line} compression prompt differs from frozen manifest")
        evidence = (directory / f"{qid}-{line}.evidence.json").read_text()
        require(count(evidence) == row["original_text_tokens"]
                and row["text_budget"] == count(evidence) // 8, f"{qid}/{line} token accounting differs")
        evidence_value = json.loads(evidence)
        require(set(evidence_value) == {"history"} and all(
            set(session) == {"date", "turns"} and all(set(turn) == {"role", "content"}
            for turn in session["turns"]) for session in evidence_value["history"]),
            f"{qid}/{line} evidence schema leaks labels")
        input_messages = [
            {"role": "system", "content": snapshot["workflow"]["system_prompt"]},
            {"role": "user", "content": "[source=history; format=none]\n" + evidence},
            {"role": "user", "content": snapshot["workflow"]["analyses"][0]["user_prompt"]},
        ]
        stage = "analysis" if line == "A" else "compress"
        require(by_call[f"{qid}/{line}/business/{stage}"]["request_body"]["messages"] == input_messages,
                f"{qid}/{line} unexpected source/task messages")
        if line != "A":
            downstream_messages = [input_messages[0], {"role": "user", "content": summary},
                                   {"role": "user", "content": snapshot["workflow"]["fan_in"]["user_prompt"]}]
            require(by_call[f"{qid}/{line}/business/analysis"]["request_body"]["messages"] == downstream_messages,
                    f"{qid}/{line} downstream input differs/leaks raw evidence")
        if line == "C":
            b = by_call[f"{qid}/B/business/compress"]["request_body"]
            c = by_call[f"{qid}/C/business/compress"]["request_body"]
            require({k: v for k, v in b.items() if k != "messages"} ==
                    {k: v for k, v in c.items() if k != "messages"}
                    and b["messages"][:-1] == c["messages"][:-1], f"{qid} B/C differ beyond prompt")
    for request in requests:
        body = request["request_body"]
        call_id = request["call_id"]
        judge = call_id.endswith("/judge")
        compress = call_id.endswith("/compress")
        require(body["stream"] is True and "streaming" not in body, f"{call_id} not streaming")
        require(request.get("finish_reason") == "stop", f"{call_id} truncated/nonstop")
        require(request.get("usage") is not None, f"{call_id} usage missing")
        require(body["model"] == ("gpt-6-luna" if judge or compress else "gpt-6.1-sol"),
                f"{call_id} wrong model")
        require(body["reasoning_effort"] == ("max" if judge else "xhigh" if compress else "medium"),
                f"{call_id} wrong effort")
        if judge:
            require(body.get("temperature") == 0, f"{call_id} judge temperature")
        if not compress:
            require(body.get("max_completion_tokens") == 4096, f"{call_id} output budget differs")
        if compress:
            qid, line = call_id.split("/")[:2]
            snapshot = json.loads((directory / f"{qid}-{line}.snapshot.json").read_text())
            expected_prompt = snapshot["workflow"]["analyses"][0]["user_prompt"]
            require(body["messages"][-1]["content"] == expected_prompt, f"{call_id} compression task differs")
            require(body["max_tokens"] == next(r["text_budget"] for r in reports
                                              if r["question_id"] == qid and r["line"] == line),
                    f"{call_id} budget differs")
            require("Compress the history to at most" not in json.dumps(body["messages"]),
                    f"{call_id} budget in prompt")
    require(all(r.get("status") == "completed" and r.get("api_key_id") == 11
                and r.get("cost_status") == "resolved" for r in ledger), "ledger incomplete/wrong key")
    require(len(ledger) == len(requests), "ledger size differs")
    for row in ledger:
        if row.get("cost_status") != "resolved":
            continue
        body = by_call[row["call_id"]]["request_body"]
        require(row["model_id"] == body["model"] and row["reasoning_effort"] == body["reasoning_effort"]
                and row["stream"] == 1, f"{row['call_id']} ledger request parameters differ")
    require((directory / "workflows.sqlite3").exists(), "workflow database missing")
    costs = {}
    for line in "ABC":
        values = [r for r in ledger if f"/{line}/" in r["call_id"]]
        for stage in ("business", "judge"):
            costs[f"{line}_{stage}"] = str(sum(
                (Decimal(str(u["total_cost"])) for r in values if f"/{stage}" in r["call_id"]
                 for u in r.get("usage", []) if u["total_cost"] is not None), Decimal(0),
            ))
    return {"passed": not issues, "issues": issues, "question_ids": sorted({q for q, _ in expected}),
            "selected": split["selected"], "compression_prompts": run.get("compression_prompts"),
            "costs": costs, "request_count": len(requests), "cache_note": "actual cost includes cache",
            "upstream_executions": [{"call_id": r["call_id"], "executions": r.get("executions", [])}
                                    for r in ledger],
            "official_scorer_commit": "9e0b455f4ef0e2ab8f2e582289761153549043fc",
            "scorer_sha256": hashlib.sha256(Path(__file__).with_name("longmemeval_official.py").read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    with sqlite3.connect(f"file:{args.database}?mode=ro", uri=True) as connection:
        ledger = match_ledger(read_requests(args.output), connection)
    (args.output / "axonhub-ledger.json").write_text(json.dumps(ledger, indent=2))
    audit = audit_run(args.output, ledger)
    (args.output / "audit.json").write_text(json.dumps(audit, indent=2))
    print(json.dumps(audit))
    if not audit["passed"]:
        raise SystemExit("technical audit failed; stop expansion")


if __name__ == "__main__":
    main()
