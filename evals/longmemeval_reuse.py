"""Reuse completed paired routes explicitly, preserving failed source artifacts."""

import json
import shutil


def reuse_completed(source, output, split, prompts, expected_snapshots):
    def read(name):
        return json.loads((source / name).read_text())

    previous_split = read("split.json")
    if previous_split != split or read("compression-prompts.json") != prompts:
        raise ValueError("reuse dataset/split/compression prompts differ")
    reports, judgments = read("reports.json"), read("judgments.json")
    successful_judges = {(j["question_id"], j["line"]) for j in judgments if j["status"] == "success"}
    completed = {(r["question_id"], r["line"]) for r in reports
                 if r["status"] == "completed" and (r["question_id"], r["line"]) in successful_judges}
    requests = [json.loads(line) for line in (source / "requests.jsonl").read_text().splitlines()]
    reused_requests = []
    for qid, line in completed:
        prefix = f"{qid}-{line}"
        snapshot = read(f"{prefix}.snapshot.json")
        expected = expected_snapshots[(qid, line)]
        if snapshot["workflow"] != expected["workflow"] or snapshot["ai"] != expected["ai"]:
            raise ValueError(f"reuse workflow/model parameters differ: {prefix}")
        if (source / f"{prefix}.evidence.json").read_text() != (output / f"{prefix}.evidence.json").read_text():
            raise ValueError(f"reuse evidence differs: {prefix}")
        calls = [r for r in requests if r["call_id"].startswith(f"{qid}/{line}/")]
        if len(calls) != (2 if line == "A" else 3) or any(
            r["status"] != "success" or r.get("finish_reason") != "stop" for r in calls
        ):
            raise ValueError(f"reuse requests incomplete: {prefix}")
        reused_requests.extend(calls)
        for suffix in ("snapshot.json", "result.json", "history.json"):
            shutil.copyfile(source / f"{prefix}.{suffix}", output / f"{prefix}.{suffix}")
    reused_requests.sort(key=lambda r: r["started_at"])
    provenance = {"source": str(source), "completed_pairs": sorted(completed),
                  "reused_response_ids": [r["response_id"] for r in reused_requests],
                  "excluded_requests": [r for r in requests if r not in reused_requests],
                  "excluded_cost_note": "source failed/unscored requests remain part of total experimental cost"}
    return ([r for r in reports if (r["question_id"], r["line"]) in completed],
            [j for j in judgments if (j["question_id"], j["line"]) in completed],
            reused_requests, provenance)
