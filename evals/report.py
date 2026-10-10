"""Aggregate exact usage and paired judge scores; disclose missing evidence."""

import argparse
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import mean

from .inputs import CONDITIONS


def retained_rows(item, case):
    """Count complete field sets, rather than calling token loss compression."""
    format = CONDITIONS[item["condition"]][0]
    result = {}
    for view in item["views"]:
        original = case["sources"][view["source_id"]]
        if not isinstance(original, list):
            continue
        if view["omitted"] or not view["text"]:
            result[view["source_id"]] = {"retained": 0, "original": len(original)}
            continue
        body = view["text"].partition("\n")[2]
        if format == "ison":
            import ison_parser
            records = ison_parser.loads(body).to_dict()["data"]
        elif format == "zon":
            import zon
            records = zon.decode(body)
        else:
            records = json.loads(body)
        complete = sum(isinstance(r, dict) and r.keys() == original[0].keys() for r in records)
        result[view["source_id"]] = {"retained": complete, "original": len(original)}
    return result


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def paired_results(judgments):
    grouped = defaultdict(list)
    for record in judgments:
        if record["status"] != "success":
            continue
        condition = next(c for c in record["labels"].values() if c != "json_full")
        winner = record["judgment"]["winner"]
        grouped[(record["case"], condition)].append("tie" if winner == "tie" else record["labels"][winner])
    return [{"case": case, "condition": condition, "orientations": len(winners),
             "position_conflict": len(winners) == 2 and winners[0] != winners[1],
             "winner": winners[0] if len(winners) == 2 and winners[0] == winners[1] else None}
            for (case, condition), winners in grouped.items()]


def summarize(directory):
    requests = read_lines(directory / "requests.jsonl")
    costs = {r["call_id"]: r for r in json.loads((directory / "costs.json").read_text())}
    judgments = read_lines(directory / "judge.jsonl")
    candidates = json.loads((directory / "candidates.json").read_text())
    inputs = read_lines(directory / "inputs.jsonl")
    cases = {r["id"]: r for r in json.loads((directory / "cases.json").read_text())}
    retention = [{"case": i["case"], "condition": i["condition"],
                  "rows": retained_rows(i, cases[i["case"]])} for i in inputs]
    scores = defaultdict(list)
    for record in judgments:
        if record["status"] != "success":
            continue
        for label, condition in record["labels"].items():
            scores[(record["case"], condition)].append(record["judgment"]["scores"][label])
    pairs = paired_results(judgments)
    rows = []
    for condition in CONDITIONS:
        calls = [r for r in requests if "/judge/" not in r["call_id"] and r["call_id"].split("/")[1] == condition]
        resolved = [costs[r["call_id"]] for r in calls if costs[r["call_id"]]["status"] == "resolved"]
        usage = [u for c in resolved for u in c["usage"]]
        per_case = {ident: mean(mean(s.values()) for s in values)
                    for (ident, variant), values in scores.items() if variant == condition}
        public = [score for ident, score in per_case.items() if cases[ident]["provenance"] == "public_kaggle_sample"]
        matching_pairs = [p for p in pairs if p["condition"] == condition]
        rows.append({
            "condition": condition, "successful_cases": sum(c["status"] == "success" for c in candidates if c["condition"] == condition),
            "business_calls": len(calls), "resolved_business_calls": len(resolved),
            "mean_input_characters": mean(i["characters"] for i in inputs if i["condition"] == condition),
            "prompt_tokens": sum(u["prompt_tokens"] for u in usage),
            "cached_prompt_tokens": sum(u["prompt_cached_tokens"] for u in usage),
            "completion_tokens": sum(u["completion_tokens"] for u in usage),
            "total_tokens": sum(u["total_tokens"] for u in usage),
            "business_cost_usd": str(sum((Decimal(str(u["total_cost"])) for u in usage), Decimal(0))),
            "cost_complete": len(calls) == len(resolved),
            "actual_models": sorted({u["model_id"] for u in usage}),
            "kaggle_score": mean(public) if public else None,
            "overall_score": mean(per_case.values()) if per_case else None,
            "position_conflicts": sum(p["position_conflict"] for p in matching_pairs),
            "paired_wins": sum(p["winner"] == condition for p in matching_pairs),
            "paired_ties": sum(p["winner"] == "tie" for p in matching_pairs),
            "score_cases": len(per_case),
        })
    judge_calls = [r for r in requests if "/judge/" in r["call_id"]]
    judge_usage = [u for r in judge_calls for u in costs[r["call_id"]].get("usage", [])]
    max_verified = all(costs[r["call_id"]].get("request", {}).get("reasoning_effort") == "max" for r in judge_calls)
    judge_cost_complete = all(costs[r["call_id"]]["status"] == "resolved" for r in judge_calls)
    judge_observed_cost = str(sum((Decimal(str(u["total_cost"])) for u in judge_usage), Decimal(0)))
    result = {"frequency": "manual, one trial per condition; AB and BA judges", "cases": len(cases),
              "rows": rows, "pairs": pairs, "input_retention": retention, "judge_calls": len(judge_calls),
              "judge_max_verified": max_verified,
              "judge_cost_usd": judge_observed_cost if judge_cost_complete else None,
              "judge_observed_cost_usd": judge_observed_cost,
              "judge_cost_complete": judge_cost_complete,
              "limitations": ["Small pilot: two fixed public Kaggle cases; no statistical superiority claim.",
                              "Scores are LLM-assisted, without independent human validation.",
                              "Cache effects and provider routing are observed, not held constant.",
                              "The 100-error/100-recent selection is a test window and cannot estimate source-file failure rates."]}
    (directory / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.directory), ensure_ascii=False))
