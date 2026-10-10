"""Pinned, small JSON-normalized sample from a public Kaggle log dataset."""

import hashlib
import json
from pathlib import Path

MANIFEST = json.loads(Path(__file__).with_name("dataset.json").read_text())


def _identifier(record: dict) -> dict:
    """Return stable identifiers that a report can cite and a judge can verify."""
    for key in ("eventID", "requestID", "uuid", "id"):
        value = record.get(key)
        if value not in (None, ""):
            return {key: value}
    return {}


def _reference_answer(records: list[dict], reference: dict) -> dict:
    errors = [record for record in records if record["kind"] == "error"]
    recent = [record for record in records if record["kind"] == "recent"]

    def evidence(rows):
        return [{"record_id": row["record_id"], "source_row": row["source_row"],
                 "at": row["at"], "kind": row["kind"], "identifiers": _identifier(row)}
                for row in rows[:3]]

    return {
        "scope": {"selected_records": len(records), "error_records": len(errors),
                  "recent_records": len(recent),
                  "required_order": ["error_or_failure", "recent_success_or_other"]},
        "source_file": {"records": reference["full_source_records"],
                        "error_records": reference["full_source_counts"]["errors"],
                        "success_or_other_records": reference["full_source_counts"]["success_or_other"]},
        "required_error_evidence": evidence(errors),
        "required_recent_evidence": evidence(recent),
        "required_boundaries": [
            "The 100 error/failure plus 100 recent selection is a fixed test window, not a source-file rate.",
            "Only visible fields support conclusions; no repair was executed.",
        ],
        "forbidden_claims": [
            "Do not claim the selected 100/100 ratio is the full-file failure rate.",
            "Do not claim a root cause or completed remediation without evidence.",
        ],
    }


def public_cases(data: bytes) -> list[dict]:
    if hashlib.sha256(data).hexdigest() != MANIFEST["sample_sha256"]:
        raise ValueError("Kaggle sample SHA-256 mismatch")
    fixture = json.loads(data)
    if fixture["dataset"]["id"] != MANIFEST["id"]:
        raise ValueError("Unexpected Kaggle sample dataset")
    cases = []
    for item in fixture["cases"]:
        records = []
        for original in item["records"]:
            record = {key: original[key] for key in ("record_id", "source_row", "kind", "at")}
            record.update(original["fields"])
            records.append(record)
        errors = [record for record in records if record["kind"] == "error"]
        recent = [record for record in records if record["kind"] == "recent"]
        reference = dict(item["reference"])
        reference["focus"] = [
            {"id": record["record_id"], "kind": record["kind"], "at": record["at"]}
            for record in records[:3]
        ]
        cases.append({
            "id": item["id"],
            "provenance": "public_kaggle_sample",
            "task": item["task"],
            "sources": {"errors": errors, "recent": recent},
            "reference": reference,
            "reference_answer": _reference_answer(records, reference),
        })
    return cases


def cases(data: bytes) -> list[dict]:
    return public_cases(data)
