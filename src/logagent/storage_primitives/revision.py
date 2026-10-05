"""Small helpers for opaque content ETags and monotonic integer revisions."""

from __future__ import annotations

from .digest import sha256_bytes


def etag_for_bytes(value: bytes) -> str:
    """Return a quoted strong ETag suitable for an HTTP If-Match header."""
    return f'"{sha256_bytes(value)}"'


def if_match(actual: str | None, expected: str) -> bool:
    """Apply the strong If-Match rules used by file and revision adapters."""
    if not isinstance(expected, str) or not expected:
        raise ValueError("If-Match must be a non-empty string")
    if expected == "*":
        return actual is not None
    candidates = {candidate.strip() for candidate in expected.split(",")}
    return actual is not None and actual in candidates


def next_revision(current: int) -> int:
    if type(current) is not int or current < 0:
        raise ValueError("revision must be a non-negative integer")
    return current + 1
