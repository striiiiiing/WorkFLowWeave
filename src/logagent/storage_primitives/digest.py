"""Canonical serialization and content digests."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from logagent.redaction import redact_data

__all__ = ["canonical_json", "digest_json", "redact_data", "sha256_bytes"]


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))
