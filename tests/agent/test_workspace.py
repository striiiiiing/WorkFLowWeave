import asyncio
import hashlib
import shutil
import threading
from pathlib import Path

import pytest

import workflowweave.agent.workspace.files as workspace_module
from workflowweave.agent.workspace import RuntimeIdentity, WorkspaceBackend
from workflowweave.errors import WorkFLowWeaveError

DEFAULT_LIMIT = 200
OUTPUT_BYTES = 16 * 1024 * 1024


async def backend_for(tmp_path: Path) -> WorkspaceBackend:
    backend = WorkspaceBackend(tmp_path / "workspace", tmp_path / "runtime")
    await backend.initialize()
    return backend


def assert_error(exc_info: pytest.ExceptionInfo[WorkFLowWeaveError], code: str) -> None:
    assert exc_info.value.code == code


async def read_backend(backend: WorkspaceBackend, path: str, **kwargs):
    kwargs.setdefault("default_limit", DEFAULT_LIMIT)
    kwargs.setdefault("output_bytes", OUTPUT_BYTES)
    return await backend.read(path, **kwargs)


async def grep_backend(backend: WorkspaceBackend, pattern: str, **kwargs):
    kwargs.setdefault("default_limit", DEFAULT_LIMIT)
    kwargs.setdefault("output_bytes", OUTPUT_BYTES)
    return await backend.grep(pattern, **kwargs)


async def test_initialize_instructions_and_workspace_layout(tmp_path):
    backend = await backend_for(tmp_path)
    expected = "只在需要时读取 Memory。\n保留可继续执行的上下文。"
    (backend.root / "AGENTS.md").write_text(expected, encoding="utf-8")

    assert await backend.instructions() == expected
    assert {
        path.name for path in backend.root.iterdir()
    } >= {"AGENTS.md", "Memory", "History", "Catalog", "Artifacts"}
    assert {
        path.name for path in backend.runtime.iterdir()
    } >= {"Catalog", "Artifacts", "History"}


async def test_runtime_self_is_session_scoped_readonly_and_not_searchable(tmp_path):
    base = WorkspaceBackend(tmp_path / "workspace", tmp_path / "runtime")
    await base.initialize()
    first = base.for_identity(RuntimeIdentity("s1", "t1", "b1", model="m1"))
    second = base.for_identity(RuntimeIdentity("s2", "t2", "b2", model="m2"))

    first_view = await read_backend(first, "Runtime/self.json")
    second_view = await read_backend(second, "Runtime/self.json")
    assert '"session_id": "s1"' in first_view["content"]
    assert '"session_id": "s2"' in second_view["content"]
    assert '"session_id": "s2"' not in first_view["content"]
    assert first_view["readonly"] and first_view["hash"] != second_view["hash"]

    with pytest.raises(WorkFLowWeaveError) as write_error:
        await first.write("Runtime/self.json", "overwrite", "{}")
    assert_error(write_error, "read_only")
    with pytest.raises(WorkFLowWeaveError) as grep_error:
        await first.grep("session_id", path="Runtime/self.json",
                          default_limit=DEFAULT_LIMIT, output_bytes=OUTPUT_BYTES)
    assert_error(grep_error, "read_only")


async def test_read_paginates_and_hashes_complete_file(tmp_path):
    backend = await backend_for(tmp_path)
    content = "zero\none\ntwo\nthree\n"
    await backend.write("Memory/page.txt", "overwrite", content)

    first = await read_backend(backend, "Memory/page.txt", offset=1, limit=2)
    second = await read_backend(backend, "Memory/page.txt", offset=3, limit=2)

    expected_hash = hashlib.sha256(content.encode()).hexdigest()
    assert first == {
        "status": "success",
        "kind": "file",
        "path": "Memory/page.txt",
        "content": "one\ntwo\n",
        "hash": expected_hash,
        "offset": 1,
        "next_offset": 3,
        "total_lines": 4,
        "readonly": False,
    }
    assert second["content"] == "three\n"
    assert second["hash"] == expected_hash
    assert second["next_offset"] is None


async def test_read_uses_injected_config_defaults(tmp_path):
    backend = await backend_for(tmp_path)
    await backend.write("Memory/defaults.txt", "overwrite", "default values\n")

    result = await read_backend(backend, "Memory/defaults.txt")

    assert result["content"] == "default values\n"
    assert result["next_offset"] is None


async def test_read_enforces_output_budget_without_partial_success(tmp_path):
    backend = await backend_for(tmp_path)
    await backend.write("Memory/large-line.txt", "overwrite", "123456\n")

    with pytest.raises(WorkFLowWeaveError) as exc_info:
        await read_backend(backend, "Memory/large-line.txt", output_bytes=5)

    assert_error(exc_info, "output_limit_exceeded")


async def test_write_modes_and_unique_replace(tmp_path):
    backend = await backend_for(tmp_path)

    overwrite = await backend.write("Memory/edit.txt", "overwrite", "before\n")
    append = await backend.write("Memory/edit.txt", "append", "after\n")
    replace = await backend.write(
        "Memory/edit.txt",
        "replace",
        "updated",
        old_text="before",
    )

    assert overwrite["bytes"] == len(b"before\n")
    assert append["bytes"] == len(b"before\nafter\n")
    assert replace["bytes"] == len(b"updated\nafter\n")
    assert (backend.root / "Memory/edit.txt").read_text() == "updated\nafter\n"

    await backend.write("Memory/repeated.txt", "overwrite", "same same")
    with pytest.raises(WorkFLowWeaveError) as exc_info:
        await backend.write(
            "Memory/repeated.txt",
            "replace",
            "new",
            old_text="same",
        )
    assert_error(exc_info, "replace_conflict")
    assert (backend.root / "Memory/repeated.txt").read_text() == "same same"


async def test_expected_hash_and_create_only_conflicts_preserve_content(tmp_path):
    backend = await backend_for(tmp_path)
    await backend.write("Memory/versioned.txt", "overwrite", "v1")
    current_hash = hashlib.sha256(b"v1").hexdigest()

    await backend.write(
        "Memory/versioned.txt",
        "overwrite",
        "v2",
        expected_hash=current_hash,
    )
    with pytest.raises(WorkFLowWeaveError) as stale:
        await backend.write(
            "Memory/versioned.txt",
            "overwrite",
            "should-not-write",
            expected_hash=current_hash,
        )
    assert_error(stale, "file_conflict")
    assert (backend.root / "Memory/versioned.txt").read_text() == "v2"

    await backend.write(
        "Memory/create-only.txt",
        "overwrite",
        "first",
        expected_hash="*",
    )
    with pytest.raises(WorkFLowWeaveError) as existing:
        await backend.write(
            "Memory/create-only.txt",
            "overwrite",
            "second",
            expected_hash="*",
        )
    assert_error(existing, "file_conflict")
    assert (backend.root / "Memory/create-only.txt").read_text() == "first"


async def test_sandbox_rejects_escape_but_disabled_sandbox_allows_host_path(tmp_path):
    backend = await backend_for(tmp_path)
    outside = tmp_path / "host-file.txt"
    outside.write_text("host data", encoding="utf-8")

    with pytest.raises(WorkFLowWeaveError) as parent_escape:
        await read_backend(backend, "../host-file.txt")
    assert_error(parent_escape, "path_forbidden")

    with pytest.raises(WorkFLowWeaveError) as absolute_escape:
        await read_backend(backend, str(outside))
    assert_error(absolute_escape, "path_forbidden")

    assert (await read_backend(backend, str(outside), sandbox=False))["content"] == "host data"
    await backend.write(str(outside), "overwrite", "changed", sandbox=False)
    assert outside.read_text() == "changed"


async def test_directory_and_leaf_symlinks_are_rejected(tmp_path):
    backend = await backend_for(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "target.txt").write_text("outside", encoding="utf-8")
    leaf = backend.root / "leaf.txt"
    directory = backend.root / "directory"
    leaf.symlink_to(outside / "target.txt")
    directory.symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkFLowWeaveError) as leaf_read:
        await read_backend(backend, "leaf.txt")
    assert_error(leaf_read, "path_forbidden")

    with pytest.raises(WorkFLowWeaveError) as leaf_write:
        await backend.write("leaf.txt", "overwrite", "changed")
    assert_error(leaf_write, "path_forbidden")
    assert (outside / "target.txt").read_text() == "outside"

    with pytest.raises(WorkFLowWeaveError) as directory_read:
        await read_backend(backend, "directory/target.txt")
    assert_error(directory_read, "path_forbidden")


async def test_directory_swap_during_open_is_rejected(tmp_path, monkeypatch):
    backend = await backend_for(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    race_dir = backend.root / "race"
    race_dir.mkdir()

    original_open = workspace_module.os.open
    swapped = False

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == "race" and dir_fd is not None and not swapped:
            swapped = True
            shutil.rmtree(race_dir)
            race_dir.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(workspace_module.os, "open", racing_open)
    try:
        with pytest.raises(WorkFLowWeaveError) as exc_info:
            await read_backend(backend, "race/secret.txt")
    finally:
        if race_dir.is_symlink():
            race_dir.unlink()
    assert_error(exc_info, "path_forbidden")
    assert swapped


async def test_runtime_views_are_readonly_and_history_notes_remain_editable(tmp_path):
    backend = await backend_for(tmp_path)
    await backend.save_runtime("Catalog/gen/schema.json", b'{"tool":"read"}')
    await backend.save_runtime("Artifacts/session/output.txt", b"artifact")
    await backend.save_runtime("History/session/events.jsonl", b'{"event":"done"}\n')

    catalog = await read_backend(backend, "Catalog/gen/schema.json")
    artifact = await read_backend(backend, "Artifacts/session/output.txt")
    history = await read_backend(backend, "History/session/events.jsonl")
    assert catalog["content"] == '{"tool":"read"}'
    assert artifact["content"] == "artifact"
    assert history["content"] == '{"event":"done"}\n'
    assert catalog["readonly"] is artifact["readonly"] is history["readonly"] is True

    for path in (
        "Catalog/gen/schema.json",
        "Artifacts/session/output.txt",
        "History/session/events.jsonl",
    ):
        with pytest.raises(WorkFLowWeaveError) as exc_info:
            await backend.write(path, "overwrite", "tampered")
        assert_error(exc_info, "read_only")

    await backend.write("History/session.md", "overwrite", "editable note")
    await backend.write("History/session.md", "append", "\nnext")
    note = await read_backend(backend, "History/session.md")
    assert note["content"] == "editable note\nnext"
    assert note["readonly"] is False


async def test_directory_listing_paginates_and_maps_runtime_roots(tmp_path):
    backend = await backend_for(tmp_path)
    await backend.save_runtime("Catalog/gen/schema.json", b"{}")
    await backend.save_runtime("Artifacts/session/result.txt", b"result")
    await backend.save_runtime("History/session/events.jsonl", b"{}")
    await backend.write("Memory/local.txt", "overwrite", "local")

    root_page = await read_backend(backend, "", offset=0, limit=3)
    root_names = [entry["name"] for entry in root_page["entries"]]
    assert root_names == ["Artifacts", "Catalog", "History"]
    assert root_page["next_offset"] == 3
    assert {
        entry["name"]: entry["readonly"] for entry in root_page["entries"]
    } == {"Artifacts": True, "Catalog": True, "History": False}

    history_page = await read_backend(backend, "History", limit=1)
    assert history_page["entries"] == [{
        "name": "session",
        "kind": "directory",
        "symlink": False,
        "readonly": True,
    }]
    assert history_page["next_offset"] is None


async def test_cancellation_waits_for_file_worker_before_return(tmp_path, monkeypatch):
    backend = await backend_for(tmp_path)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    marker = backend.root / "Memory" / "cancelled.txt"

    def blocking_write(path, mode, content, old_text, expected_hash, sandbox):
        started.set()
        release.wait()
        marker.write_text("worker finished", encoding="utf-8")
        finished.set()
        return {"status": "success", "path": path, "hash": "unused", "bytes": 0}

    monkeypatch.setattr(backend, "_write", blocking_write)
    operation = asyncio.create_task(
        backend.write("Memory/cancelled.txt", "overwrite", "ignored")
    )
    observer_started = asyncio.Event()

    async def observe_cancelled_operation():
        observer_started.set()
        try:
            await operation
        except asyncio.CancelledError:
            return finished.is_set()
        return finished.is_set()

    try:
        await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=5)
        operation.cancel()
        observer = asyncio.create_task(observe_cancelled_operation())
        await asyncio.wait_for(observer_started.wait(), timeout=5)
        release.set()
        returned_after_worker = await asyncio.wait_for(observer, timeout=5)
    finally:
        release.set()
        if not operation.done():
            await operation

    assert returned_after_worker is True
    assert finished.is_set()
    assert marker.read_text() == "worker finished"


async def test_grep_searches_logical_runtime_paths_and_honors_glob(tmp_path):
    backend = await backend_for(tmp_path)
    await backend.write("Memory/notes.md", "overwrite", "needle in notes\n")
    await backend.write("Memory/notes.txt", "overwrite", "needle in text\n")
    await backend.save_runtime("Catalog/gen/schema.json", b"needle in catalog\n")
    await backend.save_runtime("Artifacts/session/output.txt", b"needle in artifact\n")
    await backend.save_runtime("History/session/events.jsonl", b"needle in history\n")

    notes = await grep_backend(backend, "needle", path="Memory", glob="*.md")
    catalog = await grep_backend(backend, "needle", path=".", glob="Catalog/**/*.json")

    assert notes["status"] == "success"
    assert notes["truncated"] is False
    assert notes["matches"] == [{
        "path": "Memory/notes.md",
        "line": 1,
        "text": "needle in notes",
    }]
    assert catalog["matches"] == [{
        "path": "Catalog/gen/schema.json",
        "line": 1,
        "text": "needle in catalog",
    }]


async def test_grep_truncates_visible_match_results_and_output_budget(tmp_path):
    backend = await backend_for(tmp_path)
    lines = "\n".join(f"needle-{index}" for index in range(1, 5)) + "\n"
    await backend.write("Memory/hits.txt", "overwrite", lines)

    limited = await grep_backend(backend, "needle", path="Memory/hits.txt", limit=2)
    capped = await grep_backend(
        backend,
        "needle",
        path="Memory/hits.txt",
        limit=20,
        output_bytes=16,
    )

    assert limited == {
        "status": "success",
        "matches": [
            {"path": "Memory/hits.txt", "line": 1, "text": "needle-1"},
            {"path": "Memory/hits.txt", "line": 2, "text": "needle-2"},
        ],
        "truncated": True,
        "next": "缩小 path/glob 或提高 limit",
    }
    assert capped["status"] == "output_limit_exceeded"
    assert capped["truncated"] is True
    assert capped["saved_bytes"] <= 16
    assert capped["matches"] == []


async def test_grep_reports_invalid_regular_expression(tmp_path):
    backend = await backend_for(tmp_path)
    await backend.write("Memory/search.txt", "overwrite", "needle\n")

    with pytest.raises(WorkFLowWeaveError) as exc_info:
        await grep_backend(backend, "[", path="Memory/search.txt")

    assert_error(exc_info, "grep_failed")
    assert "diagnostic" in exc_info.value.details


async def test_grep_does_not_follow_symlink_files_or_directories(tmp_path):
    backend = await backend_for(tmp_path)
    target_dir = backend.root / "Memory" / "real"
    target_dir.mkdir()
    target = target_dir / "target.txt"
    target.write_text("needle in target\n", encoding="utf-8")
    (backend.root / "Memory" / "linked.txt").symlink_to(target)
    (backend.root / "Memory" / "linked-dir").symlink_to(target_dir, target_is_directory=True)

    result = await grep_backend(backend, "needle", path="Memory")

    assert result["matches"] == [{
        "path": "Memory/real/target.txt",
        "line": 1,
        "text": "needle in target",
    }]
    with pytest.raises(WorkFLowWeaveError) as exc_info:
        await grep_backend(backend, "needle", path="Memory/linked.txt")
    assert_error(exc_info, "path_forbidden")
