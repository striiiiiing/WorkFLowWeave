"""Process and coroutine lock helpers for short storage critical sections."""

from __future__ import annotations

import asyncio
import fcntl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


@contextmanager
def file_lock(path: str | Path) -> Iterator[None]:
    """Hold an exclusive advisory lock on a stable lock file."""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


async def run_blocking_owned(
    function: Callable[..., T], /, *args: Any,
    cancel_result: Callable[[T], None] | None = None,
    **kwargs: Any,
) -> T:
    """Finish a worker-thread operation before propagating caller cancellation.

    A cancelled coroutine must not release its surrounding async lock while a
    filesystem worker is still mutating the same data. Repeated cancellation
    is deferred until the worker exits; worker failures remain visible.
    """
    task = asyncio.create_task(asyncio.to_thread(partial(function, *args, **kwargs)))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        result = task.result()
        if cancel_result is not None:
            cancel_result(result)
        raise
