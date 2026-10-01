"""Process-wide Agent read capacity and exclusive execution."""

import asyncio
from contextlib import asynccontextmanager

import aiorwlock


class ToolScheduler:
    def __init__(self, read_concurrency: int):
        self.read_concurrency = read_concurrency
        self._slots = asyncio.Semaphore(read_concurrency)
        self._resize_lock = asyncio.Lock()
        self._lock = aiorwlock.RWLock()
        self.reading = 0
        self.writing = 0
        self.queued = 0

    async def resize(self, read_concurrency: int) -> None:
        """Change workspace capacity without replacing the lock or semaphore.

        A new turn applies its captured limit. Shrinking waits for existing
        readers; cancellation returns any permits already retired.
        """
        async with self._resize_lock:
            retired = 0
            try:
                for _ in range(max(0, self.read_concurrency - read_concurrency)):
                    await self._slots.acquire()
                    retired += 1
            except BaseException:
                for _ in range(retired):
                    self._slots.release()
                raise
            for _ in range(max(0, read_concurrency - self.read_concurrency)):
                self._slots.release()
            self.read_concurrency = read_concurrency

    @property
    def status(self):
        return {"read_concurrency": self.read_concurrency, "write_concurrency": 1,
                "reading": self.reading, "writing": self.writing, "queued": self.queued}

    @asynccontextmanager
    async def acquire(self, execution: str):
        if execution not in {"read", "exclusive"}:
            raise ValueError("Unknown execution category")
        self.queued += 1
        admitted = False
        try:
            if execution == "read":
                # Waiting for capacity must not hold a reader lock and starve writers.
                async with self._slots, self._lock.reader_lock:
                    self.queued -= 1
                    admitted = True
                    self.reading += 1
                    try:
                        yield
                    finally:
                        self.reading -= 1
            else:
                async with self._lock.writer_lock:
                    self.queued -= 1
                    admitted = True
                    self.writing += 1
                    try:
                        yield
                    finally:
                        self.writing -= 1
        finally:
            if not admitted:
                self.queued -= 1
