import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from workflowweave.collection import CollectorManager, FileReferenceStore
from workflowweave.collection.invocation import CollectorInvocation
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import CollectionContext, SourceConfig
from workflowweave.workflow.input_processing import extract


def source(path="notes/example.txt", **values):
    return SourceConfig(id="file", call={"kind": "file", "file_type": "text", "path": path}, **values)


@pytest.mark.parametrize("file_type", [None, "image", "pdf", "doc"])
def test_file_type_is_explicit_and_text_only(file_type):
    call = {"kind": "file", "path": "example.txt"}
    if file_type is not None:
        call["file_type"] = file_type
    with pytest.raises(ValidationError):
        SourceConfig(id="file", call=call)


@pytest.mark.parametrize("path", ["", ".", "..", "../secret", "/etc/passwd", "a/../../secret",
                                  "bad\x00name", "C:\\secret.txt", "a/.."])
def test_paths_cannot_leave_reference_directory(tmp_path, path):
    files = FileReferenceStore(tmp_path)
    with pytest.raises(WorkFLowWeaveError) as exc:
        files.validate_path(path)
    assert exc.value.code == "path_forbidden"


def test_create_preserves_bytes_and_rejects_conflicts(tmp_path):
    files = FileReferenceStore(tmp_path)
    content = "正文\r\n\r\n  tail  \r\n".encode()
    files.create_text("nested/example.md", content)
    assert (files.root / "nested/example.md").read_bytes() == content
    assert files.read_text("nested/example.md").encode() == content
    with pytest.raises(WorkFLowWeaveError) as exc:
        files.create_text("nested/example.md", b"replacement")
    assert exc.value.code == "file_conflict"
    assert (files.root / "nested/example.md").read_bytes() == content
    assert not list(files.root.rglob(".reference-*"))


@pytest.mark.parametrize("operation", ["fsync", "link"])
def test_invalid_encoding_and_failed_publication_leave_no_partial_file(tmp_path, monkeypatch, operation):
    files = FileReferenceStore(tmp_path)
    with pytest.raises(WorkFLowWeaveError, match="UTF-8"):
        files.create_text("invalid.txt", b"\xff")
    assert not (files.root / "invalid.txt").exists()

    def fail(*args, **kwargs):
        raise PermissionError("cannot publish")

    monkeypatch.setattr(os, operation, fail)
    with pytest.raises(WorkFLowWeaveError) as exc:
        files.create_text("failed.txt", b"complete")
    assert exc.value.code == "storage_failed"
    assert list(files.root.iterdir()) == []


def test_concurrent_creates_publish_one_complete_file(tmp_path):
    files = FileReferenceStore(tmp_path)

    def create(content):
        try:
            files.create_text("same.txt", content)
            return "created"
        except WorkFLowWeaveError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(create, [b"a" * 8192, b"b" * 8192]))
    assert sorted(results) == ["created", "file_conflict"]
    assert (files.root / "same.txt").read_bytes() in [b"a" * 8192, b"b" * 8192]
    assert not list(files.root.glob(".reference-*"))


def test_symlinks_cannot_escape_and_internal_links_can_be_read(tmp_path):
    files = FileReferenceStore(tmp_path / "data")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (files.root / "escape").symlink_to(outside, target_is_directory=True)
    for action in [lambda: files.read_text("escape/secret.txt"),
                   lambda: files.create_text("escape/new.txt", b"bad")]:
        with pytest.raises(WorkFLowWeaveError) as exc:
            action()
        assert exc.value.code == "path_forbidden"
    assert not (outside / "new.txt").exists()
    files.create_text("real.txt", b"inside")
    (files.root / "link.txt").symlink_to("real.txt")
    assert files.read_text("link.txt") == "inside"
    (files.root / "dangling.txt").symlink_to("not-created.txt")
    with pytest.raises(WorkFLowWeaveError) as exc:
        files.create_text("dangling.txt", b"unexpected")
    assert exc.value.code == "file_conflict"
    assert not (files.root / "not-created.txt").exists()


def test_parent_symlink_replacement_after_validation_cannot_redirect_read(tmp_path, monkeypatch):
    files = FileReferenceStore(tmp_path / "data")
    files.create_text("parent/example.txt", b"inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "example.txt").write_bytes(b"secret")
    validate = files.validate_path

    def replace(relative):
        result = validate(relative)
        (files.root / "parent").rename(files.root / "previous")
        (files.root / "parent").symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(files, "validate_path", replace)
    with pytest.raises(WorkFLowWeaveError):
        files.read_text("parent/example.txt")


@pytest.mark.parametrize("special", ["directory", "fifo"])
def test_nonregular_files_fail_without_blocking(tmp_path, special):
    files = FileReferenceStore(tmp_path)
    path = files.root / "special"
    path.mkdir() if special == "directory" else os.mkfifo(path)
    with pytest.raises(WorkFLowWeaveError):
        files.read_text("special")


async def test_each_collection_reads_current_file_without_changing_previous_result(tmp_path):
    files = FileReferenceStore(tmp_path)
    manager = CollectorManager(None, files)
    config = source()
    manager.validate(config)  # Saving a missing reference must not read it.
    files.create_text(config.call.path, b"first")
    first = await manager.collect(config, CollectionContext("wf", "first"))
    (files.root / config.call.path).write_bytes(b"second")
    second = await manager.collect(config, CollectionContext("wf", "second"))
    assert first.raw == {"text": "first"}
    assert second.raw == {"text": "second"}
    assert second.metadata == {"kind": "file", "file_type": "text", "path": config.call.path,
                               "result_known": True}
    (files.root / config.call.path).unlink()
    missing = await manager.collect(config, CollectionContext("wf", "missing"))
    assert missing.status == "failed" and missing.error.code == "file_missing"
    assert missing.raw is None
    (files.root / config.call.path).write_bytes(b"\xff")
    invalid = await manager.collect(config, CollectionContext("wf", "invalid"))
    assert invalid.status == "failed" and invalid.error.code == "file_encoding"


@pytest.mark.parametrize("text", ["", "0", "false", "null", "[]", "{}", " \r\n"])
async def test_only_empty_file_is_empty(tmp_path, text):
    files = FileReferenceStore(tmp_path)
    files.create_text("text.txt", text.encode())
    result = await CollectorManager(None, files).collect(source("text.txt"), CollectionContext("wf", "run"))
    assert result.status == ("empty" if text == "" else "success")
    assert result.raw == {"text": text}
    assert extract(result.raw, "file")[0].original == text


async def test_public_file_invocation_has_no_mcp_arguments(tmp_path):
    files = FileReferenceStore(tmp_path)
    entry = CollectorInvocation({"file": source()}, {}, executor=CollectorManager(None, files))
    assert await entry.schema("file") == {"type": "object", "properties": {}, "additionalProperties": False}
    with pytest.raises(WorkFLowWeaveError) as exc:
        await entry.invoke("file", {"arguments": {"path": "other"}}, CollectionContext("wf", "run"))
    assert exc.value.code == "invalid_argument"


async def test_file_collection_timeout_is_explicit():
    release = threading.Event()

    class SlowFiles:
        def read_text(self, path):
            release.wait(1)
            return "late"

    try:
        result = await CollectorManager(None, SlowFiles()).collect(
            source(timeout=0.01), CollectionContext("wf", "run"),
        )
        assert result.status == "timeout" and result.error.code == "file_timeout"
        assert result.raw is None and result.metadata["result_known"] is False
    finally:
        release.set()
