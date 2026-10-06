import asyncio
import threading

import pytest

from workflowweave.storage_primitives.locks import file_lock, run_blocking_owned


@pytest.mark.asyncio
async def test_cancel_waits_until_blocking_write_finishes():
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    published = []

    def blocking_write():
        entered.set()
        release.wait(timeout=2)
        finished.set()
        return "committed"

    task = asyncio.create_task(
        run_blocking_owned(blocking_write, cancel_result=published.append)
    )
    assert await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert not finished.is_set()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    assert published == ["committed"]


def test_file_lock_creates_stable_lock_file(tmp_path):
    path = tmp_path / "locks" / "value.lock"
    with file_lock(path):
        assert path.is_file()
    assert path.is_file()
