import asyncio
import os
import shlex
import time
from pathlib import Path

import pytest

import logagent.agent.sandbox as sandbox_module
from logagent.agent.config import AgentConfig, SandboxConfig
from logagent.agent.sandbox import ShellSandbox
from logagent.agent.scheduling import ToolScheduler
from logagent.agent.workspace import WorkspaceBackend
from logagent.errors import LogAgentError


async def backend_for(tmp_path: Path) -> WorkspaceBackend:
    backend = WorkspaceBackend(tmp_path / "workspace", tmp_path / "runtime")
    await backend.initialize()
    return backend


def config(*, enabled: bool = True, network: bool = False, **overrides) -> AgentConfig:
    return AgentConfig(
        sandbox=SandboxConfig(enabled=enabled, network=network),
        **overrides,
    )


async def wait_for_path(path: Path, *, max_wait: float = 2.0) -> None:
    def wait_sync():
        deadline = time.monotonic() + max_wait
        while not path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for {path}")
            time.sleep(0.005)

    await asyncio.to_thread(wait_sync)


def pid_is_alive(pid: int) -> bool:
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        state = proc_stat.read_text(encoding="ascii").split()[2]
    except FileNotFoundError:
        return False
    if state == "Z":
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def wait_for_pid_exit(pid: int, *, max_wait: float = 2.0) -> None:
    def wait_sync():
        deadline = time.monotonic() + max_wait
        while pid_is_alive(pid):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for pid {pid}")
            time.sleep(0.01)

    await asyncio.to_thread(wait_sync)


@pytest.mark.asyncio
async def test_scheduler_allows_four_reads_and_releases_cancelled_queue(tmp_path):
    scheduler = ToolScheduler(4)
    entered: list[object] = []
    all_readers_entered = asyncio.Event()
    release = asyncio.Event()

    async def reader():
        async with scheduler.acquire("read"):
            entered.append(object())
            if len(entered) == 4:
                all_readers_entered.set()
            await release.wait()

    readers = [asyncio.create_task(reader()) for _ in range(4)]
    await asyncio.wait_for(all_readers_entered.wait(), 1)
    assert scheduler.status == {
        "read_concurrency": 4,
        "write_concurrency": 1,
        "reading": 4,
        "writing": 0,
        "queued": 0,
    }

    fifth = asyncio.create_task(reader())
    await asyncio.sleep(0.02)
    assert scheduler.status["queued"] == 1
    fifth.cancel()
    with pytest.raises(asyncio.CancelledError):
        await fifth
    assert scheduler.status["queued"] == 0

    release.set()
    await asyncio.gather(*readers)
    assert scheduler.status["reading"] == 0


@pytest.mark.asyncio
async def test_scheduler_keeps_reads_and_writes_mutually_exclusive():
    scheduler = ToolScheduler(4)
    writer_entered = asyncio.Event()
    release_writer = asyncio.Event()

    async def writer():
        async with scheduler.acquire("exclusive"):
            writer_entered.set()
            await release_writer.wait()

    writer_task = asyncio.create_task(writer())
    await asyncio.wait_for(writer_entered.wait(), 1)
    reader_entered: list[object] = []

    async def reader():
        async with scheduler.acquire("read"):
            reader_entered.append(object())

    reader_task = asyncio.create_task(reader())
    await asyncio.sleep(0.02)
    assert scheduler.status["writing"] == 1
    assert scheduler.status["reading"] == 0
    assert scheduler.status["queued"] == 1
    release_writer.set()
    await asyncio.gather(writer_task, reader_task)
    assert len(reader_entered) == 1
    assert scheduler.status["writing"] == 0
    assert scheduler.status["reading"] == 0

    scheduler = ToolScheduler(4)
    release_reader = asyncio.Event()
    reader_entered = asyncio.Event()

    async def held_reader():
        async with scheduler.acquire("read"):
            reader_entered.set()
            await release_reader.wait()

    held_reader_task = asyncio.create_task(held_reader())
    await asyncio.wait_for(reader_entered.wait(), 1)
    writer_finished = asyncio.Event()

    async def held_writer():
        async with scheduler.acquire("exclusive"):
            writer_finished.set()

    held_writer_task = asyncio.create_task(held_writer())
    await asyncio.sleep(0.02)
    assert scheduler.status["reading"] == 1
    assert scheduler.status["writing"] == 0
    assert scheduler.status["queued"] == 1
    release_reader.set()
    await asyncio.gather(held_reader_task, held_writer_task)
    assert writer_finished.is_set()
    assert scheduler.status["writing"] == 0
    assert scheduler.status["reading"] == 0


@pytest.mark.asyncio
async def test_scheduler_cancellation_releases_queued_and_active_execution():
    scheduler = ToolScheduler(1)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def held_read():
        async with scheduler.acquire("read"):
            entered.set()
            await release.wait()

    holder = asyncio.create_task(held_read())
    await asyncio.wait_for(entered.wait(), 1)

    queued = asyncio.create_task(held_read())
    await asyncio.sleep(0.02)
    assert scheduler.status["queued"] == 1
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    assert scheduler.status["queued"] == 0
    assert scheduler.status["reading"] == 1

    release.set()
    await holder
    assert scheduler.status["reading"] == 0

    active_entered = asyncio.Event()

    async def cancellable_writer():
        async with scheduler.acquire("exclusive"):
            active_entered.set()
            await asyncio.Event().wait()

    active = asyncio.create_task(cancellable_writer())
    await asyncio.wait_for(active_entered.wait(), 1)
    active.cancel()
    with pytest.raises(asyncio.CancelledError):
        await active
    assert scheduler.status == {
        "read_concurrency": 1,
        "write_concurrency": 1,
        "reading": 0,
        "writing": 0,
        "queued": 0,
    }


@pytest.mark.asyncio
async def test_shell_reports_exit_code_timeout_and_output_limit(tmp_path):
    backend = await backend_for(tmp_path)
    sandbox = ShellSandbox(backend)

    failed = await sandbox.run("printf 'out'; printf 'err' >&2; exit 7", config=config(enabled=False))
    assert failed["status"] == "failed"
    assert failed["exit_code"] == 7
    assert failed["stdout"] == "out"
    assert failed["stderr"] == "err"

    timed_out = await sandbox.run("sleep 30", timeout=0.05, config=config(enabled=False))
    assert timed_out["status"] == "timeout"

    capped = await sandbox.run(
        "yes output | head -c 4096",
        config=config(enabled=False, output_bytes=128),
    )
    assert capped["status"] == "output_limit_exceeded"
    assert capped["saved_bytes"] <= 128


@pytest.mark.asyncio
async def test_shell_uses_only_minimal_environment(tmp_path, monkeypatch):
    backend = await backend_for(tmp_path)
    sandbox = ShellSandbox(backend)
    monkeypatch.setenv("LOGAGENT_TEST_SECRET", "must-not-cross-boundary")

    result = await sandbox.run("env | sort", config=config(enabled=False))
    assert result["status"] == "success"
    environment = dict(line.split("=", 1) for line in result["stdout"].splitlines())
    assert environment == {
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PWD": str(backend.root),
        "TMPDIR": "/tmp",
    }
    assert "LOGAGENT_TEST_SECRET" not in result["stdout"]


@pytest.mark.asyncio
async def test_shell_process_group_is_cleaned_after_leader_exits(tmp_path):
    backend = await backend_for(tmp_path)
    sandbox = ShellSandbox(backend)
    pid_file = backend.root / "child.pid"

    result = await sandbox.run(
        "sleep 30 & child=$!; printf '%s' \"$child\" > child.pid; exit 0",
        config=config(enabled=False),
    )
    assert result["status"] == "success"
    child_pid = int(pid_file.read_text(encoding="ascii"))
    await wait_for_pid_exit(child_pid)


@pytest.mark.asyncio
async def test_shell_process_group_is_cleaned_when_execution_is_cancelled(tmp_path):
    backend = await backend_for(tmp_path)
    sandbox = ShellSandbox(backend)
    pid_file = backend.root / "child.pid"
    task = asyncio.create_task(
        sandbox.run(
            "sleep 30 & child=$!; printf '%s' \"$child\" > child.pid; wait \"$child\"",
            config=config(enabled=False),
        )
    )
    await wait_for_path(pid_file)
    child_pid = int(pid_file.read_text(encoding="ascii"))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await wait_for_pid_exit(child_pid)


@pytest.mark.asyncio
async def test_sandbox_workspace_is_writable(tmp_path):
    backend = await backend_for(tmp_path)
    sandbox = ShellSandbox(backend)

    result = await sandbox.run(
        "pwd; printf 'written' > created.txt; cat created.txt",
        cwd="Memory",
        config=config(),
    )
    assert result["status"] == "success"
    assert result["stdout"] == "/workspace/Memory\nwritten"
    assert (backend.root / "Memory/created.txt").read_text(encoding="utf-8") == "written"


@pytest.mark.asyncio
async def test_sandbox_runtime_catalog_artifacts_and_history_are_readonly(tmp_path):
    backend = await backend_for(tmp_path)
    await backend.save_runtime("Catalog/schema.json", b"catalog")
    await backend.save_runtime("Artifacts/output.txt", b"artifact")
    await backend.save_runtime("History/session/fact.json", b"fact")
    sandbox = ShellSandbox(backend)

    readable = await sandbox.run(
        "cat Catalog/schema.json Artifacts/output.txt History/session/fact.json",
        config=config(),
    )
    assert readable["status"] == "success"
    assert readable["stdout"] == "catalogartifactfact"

    readonly = await sandbox.run(
        "for file in Catalog/schema.json Artifacts/output.txt History/session/fact.json; do "
        "if printf changed > \"$file\"; then exit 9; fi; done; printf readonly",
        config=config(),
    )
    assert readonly["status"] == "success"
    assert readonly["stdout"] == "readonly"
    assert readonly["stderr"]
    assert (backend.runtime / "Catalog/schema.json").read_bytes() == b"catalog"
    assert (backend.runtime / "Artifacts/output.txt").read_bytes() == b"artifact"
    assert (backend.runtime / "History/session/fact.json").read_bytes() == b"fact"


@pytest.mark.asyncio
async def test_sandbox_does_not_expose_host_paths(tmp_path):
    backend = await backend_for(tmp_path)
    host_secret = tmp_path / "host-secret.txt"
    host_secret.write_text("private", encoding="utf-8")
    sandbox = ShellSandbox(backend)
    quoted_path = shlex.quote(str(host_secret))

    result = await sandbox.run(
        f"if test -e {quoted_path}; then cat {quoted_path}; exit 9; fi; printf hidden",
        config=config(),
    )
    assert result["status"] == "success"
    assert result["stdout"] == "hidden"


@pytest.mark.asyncio
async def test_sandbox_network_isolated_by_default_and_available_when_enabled(tmp_path):
    async def handle(reader, writer):
        await reader.read(4096)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        backend = await backend_for(tmp_path)
        sandbox = ShellSandbox(backend)
        command = f"curl --silent --show-error --max-time 2 http://127.0.0.1:{port}/"

        isolated = await sandbox.run(command, config=config(network=False))
        assert isolated["status"] == "failed"
        assert isolated["exit_code"] != 0
        assert isolated["stdout"] != "ok"

        connected = await sandbox.run(command, config=config(network=True))
        assert connected["status"] == "success"
        assert connected["stdout"] == "ok"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_missing_bwrap_is_explicit_and_does_not_fallback_to_host(tmp_path, monkeypatch):
    backend = await backend_for(tmp_path)
    sandbox = ShellSandbox(backend)
    host_target = tmp_path / "must-not-be-created.txt"
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: None)

    with pytest.raises(LogAgentError) as exc_info:
        await sandbox.run(f"touch {shlex.quote(str(host_target))}", config=config())
    assert exc_info.value.code == "sandbox_unavailable"
    assert not host_target.exists()


@pytest.mark.asyncio
async def test_disabled_sandbox_can_access_temporary_host_path(tmp_path):
    backend = await backend_for(tmp_path)
    host_file = tmp_path / "host-file.txt"
    host_file.write_text("host data", encoding="utf-8")
    sandbox = ShellSandbox(backend)

    result = await sandbox.run(
        f"cat {shlex.quote(str(host_file))}",
        config=config(enabled=False),
    )
    assert result["status"] == "success"
    assert result["stdout"] == "host data"
