"""Atomic local files and cancellation-safe asynchronous disk operations."""

import asyncio
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def read_json(path: Path):
    def reject(value):
        raise ValueError("Non-finite JSON number")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


async def run_io(function: Callable[..., T], *args, **kwargs) -> T:
    """A cancelled caller retains its lock until the worker actually finishes."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            if not cancelled:
                raise
            break
    if cancelled:
        if not task.cancelled():
            task.exception()  # Observe a worker failure before propagating cancellation.
        raise asyncio.CancelledError
    return task.result()
