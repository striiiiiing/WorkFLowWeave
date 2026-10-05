"""A cancelled file operation must finish before its caller releases the write lock."""

import asyncio
from functools import partial


async def file_io(function, /, *args, cancel_result=None, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(partial(function, *args, **kwargs)))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Repeated cancellation must not detach a still-mutating filesystem worker.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        result = task.result()
        if cancel_result is not None:
            cancel_result(result)
        raise
