"""Expand the fixed development sample to 2, 5 and 10 using project CLI runs."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from .audit_longmemeval import audit_run, match_ledger, read_requests
from .longmemeval_prompts import prompt_fingerprints
from .run_longmemeval import CREDENTIAL_ENV


def expansion_ranges(baseline):
    if baseline.get("compression_prompts") != prompt_fingerprints():
        raise RuntimeError("singleton compression prompt version/hash differs; do not reuse old results")
    selected = baseline["selected"]
    if len(selected) != 1 or selected[0]["shuffled_ordinal"] not in (101, 102):
        raise RuntimeError("singleton must be exactly shuffled ordinal 101 or 102")
    remaining = 102 if selected[0]["shuffled_ordinal"] == 101 else 101
    return ((2, remaining, remaining), (5, 103, 105), (10, 106, 110))


def audit(directory, database):
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        ledger = match_ledger(read_requests(directory), connection)
    (directory / "axonhub-ledger.json").write_text(json.dumps(ledger, indent=2))
    result = audit_run(directory, ledger)
    (directory / "audit.json").write_text(json.dumps(result, indent=2))
    if not result["passed"]:
        raise RuntimeError(f"technical audit failed: {directory}: {result['issues']}")
    return result


def paid_environment(database):
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT key FROM api_keys WHERE name=? AND status=? AND deleted_at=0",
            ("PC langchain", "enabled"),
        ).fetchall()
    if len(rows) != 1:
        raise RuntimeError("PC langchain enabled key must be unique")
    return {**os.environ, CREDENTIAL_ENV: rows[0][0]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--order-dataset", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--singleton", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    baseline = audit(args.singleton, args.database)
    stages = expansion_ranges(baseline)
    manifest = {"status": "running", "stages": [{"count": 1, "directory": str(args.singleton),
                                                  "audit": baseline}]}
    manifest_path = args.output / "stages.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    env = paid_environment(args.database)
    for size, start, end in stages:
        directory = args.output / f"additional-{start}-{end}"
        command = [sys.executable, "-m", "evals.run_longmemeval",
                   "--dataset", str(args.dataset), "--order-dataset", str(args.order_dataset),
                   "--start", str(start), "--end", str(end), "--seed", "20261007",
                   "--compression-ratio", "8", "--request-timeout", "900", "--interval", "12",
                   "--base-url", args.base_url, "--output", str(directory)]
        print(json.dumps({"event": "stage_started", "target_count": size, "start": start, "end": end}), flush=True)
        process = subprocess.run(command, env=env, check=False)
        if process.returncode:
            manifest.update(status="failed", failed_stage=size, exit_code=process.returncode)
            manifest_path.write_text(json.dumps(manifest, indent=2))
            raise SystemExit(process.returncode)
        try:
            result = audit(directory, args.database)
            if result.get("compression_prompts") != baseline["compression_prompts"]:
                raise RuntimeError("compression prompt version/hash changed during expansion")
        except RuntimeError:
            manifest.update(status="failed", failed_stage=size, reason="technical audit failed")
            manifest_path.write_text(json.dumps(manifest, indent=2))
            raise
        manifest["stages"].append({"count": size, "directory": str(directory), "audit": result})
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(json.dumps({"event": "stage_passed", "count": size, "audit": result}), flush=True)
    manifest["status"] = "complete"
    manifest_path.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
