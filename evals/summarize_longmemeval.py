"""Summarize audited project runs without sending any model requests."""

import argparse
import json
from decimal import Decimal
from pathlib import Path
from statistics import median


def read_json(directory, name):
    return json.loads((directory / name).read_text())


def summarize(directories):
    reports, judgments, requests, ledger, audits = [], [], [], [], []
    ordinals = {}
    holdout = None
    for directory in directories:
        audit = read_json(directory, "audit.json")
        if not audit["passed"]:
            raise ValueError(f"run has not passed technical audit: {directory}")
        if audits and audits[0].get("compression_prompts") != audit.get("compression_prompts"):
            raise ValueError("compression prompt versions differ; do not combine old and new results")
        split = read_json(directory, "split.json")
        if holdout is not None and holdout != split["holdout_ids"]:
            raise ValueError("holdout differs across runs")
        holdout = split["holdout_ids"]
        ordinals.update({s["question_id"]: s["shuffled_ordinal"] for s in split["selected"]})
        reports.extend(read_json(directory, "reports.json"))
        judgments.extend(read_json(directory, "judgments.json"))
        requests.extend(json.loads(line) for line in (directory / "requests.jsonl").read_text().splitlines())
        ledger.extend(read_json(directory, "axonhub-ledger.json"))
        audits.append(audit)
    pairs = {(r["question_id"], r["line"]) for r in reports}
    if len(pairs) != len(reports):
        raise ValueError("duplicate question/line; do not combine repeated paid runs")
    requests.sort(key=lambda r: r["started_at"])
    if any(a["finished_at"] > b["started_at"] for a, b in zip(requests, requests[1:], strict=False)):
        raise ValueError("requests overlap across runs")
    if len({r["response_id"] for r in requests}) != len(requests):
        raise ValueError("duplicate response ID across runs")
    lines = {}
    for line in "ABC":
        rows = [r for r in reports if r["line"] == line]
        scores = [j for j in judgments if j["line"] == line]
        costs = {stage: sum((Decimal(a["costs"][f"{line}_{stage}"]) for a in audits), Decimal(0))
                 for stage in ("business", "judge")}
        ratios = [r["compression_ratio"] for r in rows if r["compression_ratio"] is not None]
        cached = {}
        for stage in ("compress", "analysis", "judge"):
            usage = [u for r in ledger if f"/{line}/" in r["call_id"] and r["call_id"].endswith(f"/{stage}")
                     for u in r["usage"]]
            cached[stage] = {key: sum(u[key] or 0 for u in usage)
                             for key in ("prompt_tokens", "prompt_cached_tokens", "completion_tokens",
                                         "completion_reasoning_tokens")}
        lines[line] = {"count": len(rows), "correct": sum(s["correct"] for s in scores),
                       "accuracy": sum(s["correct"] for s in scores) / len(rows),
                       "failed": sum(r["status"] != "completed" for r in rows),
                       "business_cost": str(costs["business"]), "judge_cost": str(costs["judge"]),
                       "total_cost": str(sum(costs.values())), "usage": cached,
                       "compression_ratio": {"min": min(ratios), "median": median(ratios), "max": max(ratios)}
                       if ratios else None}
    baseline = Decimal(lines["A"]["business_cost"])
    for line in "BC":
        lines[line]["business_saving_vs_A"] = float(1 - Decimal(lines[line]["business_cost"]) / baseline)
    scores = {(j["question_id"], j["line"]): j["correct"] for j in judgments}
    return {"question_count": len(ordinals), "request_count": len(requests), "lines": lines,
            "compression_prompts": audits[0].get("compression_prompts"),
            "total_cost": str(sum((Decimal(v["total_cost"]) for v in lines.values()), Decimal(0))),
            "questions": [{"shuffled_ordinal": n, "question_id": q,
                           "correct": {line: scores[(q, line)] for line in "ABC"}}
                          for q, n in sorted(ordinals.items(), key=lambda pair: pair[1])],
            "limitations": ["development sample; final shuffled first 100 untouched",
                            "same-family Luna judge; no human agreement measured",
                            "actual bills include ordered cache effects; B/C differ only in compression prompt",
                            "8x is output ceiling, not enforced exact compression ratio"],
            "source_directories": [str(d) for d in directories]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directories", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(args.directories)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
