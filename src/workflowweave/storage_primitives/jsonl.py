"""Strict sequential JSONL read and append operations."""

from __future__ import annotations

import asyncio
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .locks import file_lock, run_blocking_owned


def parse_records(payload: bytes, *, sequence_field: str = "id") -> list[dict[str, Any]]:
    if payload and not payload.endswith(b"\n"):
        raise ValueError("JSONL ends with an incomplete record")
    records: list[dict[str, Any]] = []
    for expected, line in enumerate(payload.splitlines(), start=1):
        value = json.loads(line)
        if type(value) is not dict or type(value.get(sequence_field)) is not int:
            raise ValueError("invalid JSONL record envelope")
        if value[sequence_field] != expected:
            raise ValueError("JSONL sequence is not contiguous")
        records.append(value)
    return records


def read_records_unlocked(path: str | Path, *, sequence_field: str = "id") -> list[dict[str, Any]]:
    """Read while the caller holds the matching ``<path>.lock`` file lock."""
    path = Path(path)
    payload = path.read_bytes() if path.exists() else b""
    return parse_records(payload, sequence_field=sequence_field)


def read_records(path: str | Path, *, sequence_field: str = "id") -> list[dict[str, Any]]:
    location = Path(path)
    lock_path = location.with_name(location.name + ".lock")
    with file_lock(lock_path):
        return read_records_unlocked(location, sequence_field=sequence_field)


def append_record_unlocked(
    path: str | Path,
    record: Mapping[str, Any],
    *,
    sequence_field: str = "id",
) -> dict[str, Any]:
    """Append while the caller holds the matching ``<path>.lock`` file lock."""
    location = Path(path)
    location.parent.mkdir(parents=True, exist_ok=True)
    records = read_records_unlocked(location, sequence_field=sequence_field)
    if sequence_field in record:
        raise ValueError(f"record already contains {sequence_field!r}")
    committed = {sequence_field: len(records) + 1, **record}
    encoded = json.dumps(
        committed,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    with location.open("ab") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return committed


def append_record(
    path: str | Path,
    record: Mapping[str, Any],
    *,
    sequence_field: str = "id",
) -> dict[str, Any]:
    location = Path(path)
    lock_path = location.with_name(location.name + ".lock")
    with file_lock(lock_path):
        return append_record_unlocked(
            location, record, sequence_field=sequence_field,
        )


class JsonlStore:
    """Async cursor and notification adapter over a strict sequential JSONL file."""

    def __init__(self, path: str | Path, *, sequence_field: str = "id"):
        self.path = Path(path)
        self.sequence_field = sequence_field
        self._append_lock = asyncio.Lock()
        self._changed = asyncio.Event()
        self._revision = 0

    async def append(self, record: Mapping[str, Any]) -> dict[str, Any]:
        async with self._append_lock:
            committed = await run_blocking_owned(
                append_record,
                self.path,
                record,
                sequence_field=self.sequence_field,
                cancel_result=lambda _record: self._publish(),
            )
            self._publish()
            return committed

    async def read_after(self, sequence: int) -> list[dict[str, Any]]:
        self._validate_sequence(sequence)
        records = await run_blocking_owned(
            read_records,
            self.path,
            sequence_field=self.sequence_field,
        )
        return [record for record in records if record[self.sequence_field] > sequence]

    async def wait_after(
        self,
        sequence: int,
        *,
        wait_seconds: float,
        poll_interval: float,
    ) -> list[dict[str, Any]]:
        """Read after a cursor and wait without losing a concurrent local append.

        The event handles same-process writers; periodic rereads discover
        writers in other processes that cannot signal this instance.
        """
        self._validate_sequence(sequence)
        if (
            not math.isfinite(wait_seconds)
            or not math.isfinite(poll_interval)
            or wait_seconds < 0
            or poll_interval <= 0
        ):
            raise ValueError("wait_seconds must be non-negative and poll_interval positive")
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while True:
            revision = self._revision
            records = await self.read_after(sequence)
            if records:
                return records
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return []
            self._changed.clear()
            if self._revision != revision:
                continue
            try:
                await asyncio.wait_for(self._changed.wait(), min(remaining, poll_interval))
            except TimeoutError:
                continue

    def _publish(self) -> None:
        self._revision += 1
        self._changed.set()

    @staticmethod
    def _validate_sequence(sequence: int) -> None:
        if type(sequence) is not int or sequence < 0:
            raise ValueError("sequence cursor must be a non-negative integer")
