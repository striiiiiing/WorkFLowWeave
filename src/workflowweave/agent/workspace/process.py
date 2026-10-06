"""Bounded subprocess output and process-group cleanup, also used by ripgrep."""

import asyncio
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    status: str


def _kill_group(pid: int, stop_signal=signal.SIGKILL):
    try:
        os.killpg(pid, stop_signal)
    except ProcessLookupError:
        pass


class _OutputProtocol(asyncio.SubprocessProtocol):
    def __init__(self, output_bytes, stop_signal):
        self.limit = output_bytes
        self.size = 0
        self.buffers = {1: bytearray(), 2: bytearray()}
        self.status = "success"
        self.stop_signal = stop_signal
        self.done = asyncio.get_running_loop().create_future()

    def connection_made(self, transport):
        self.transport = transport

    def pipe_data_received(self, fd, data):
        available = max(0, self.limit - self.size)
        self.buffers[fd].extend(data[:available])
        self.size += len(data[:available])
        if len(data) > available:
            self.status = "output_limit_exceeded"
            _kill_group(self.transport.get_pid(), self.stop_signal)

    def process_exited(self):
        # The leader can exit while background children still hold the pipes open.
        _kill_group(self.transport.get_pid())

    def connection_lost(self, exc):
        if exc is None:
            self.done.set_result(None)
        else:
            self.done.set_exception(exc)


async def run_process(argv, *, cwd=None, env=None, stdin=None,
                      deadline_seconds: float | None, output_bytes: int,
                      supervise=False) -> ProcessResult:
    if supervise:
        argv = [sys.executable, "-I", str(Path(__file__).with_name("process_supervisor.py")), *argv]
    stop_signal = signal.SIGTERM if supervise else signal.SIGKILL
    protocol = _OutputProtocol(output_bytes, stop_signal)
    transport, _ = await asyncio.get_running_loop().subprocess_exec(
        lambda: protocol, *argv, cwd=cwd, env=env,
        stdin=asyncio.subprocess.DEVNULL if stdin is None else stdin,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
    )
    try:
        async with asyncio.timeout(deadline_seconds):
            await asyncio.shield(protocol.done)
    except TimeoutError:
        protocol.status = "timeout"
    finally:
        _kill_group(transport.get_pid(), stop_signal)
        cancelled = False
        while not protocol.done.done():
            try:
                await asyncio.shield(protocol.done)
            except asyncio.CancelledError:
                cancelled = True
        protocol.done.result()
        transport.close()
        if cancelled:
            raise asyncio.CancelledError
    return ProcessResult(transport.get_returncode(), bytes(protocol.buffers[1]),
                         bytes(protocol.buffers[2]), protocol.status)
