"""User-editable text files used by file collection sources."""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from workflowweave.errors import WorkFLowWeaveError


class FileReferenceStore:
    """Read and create files below one data-owned references directory.

    The store deliberately has no content cache, mtime check, or digest index.
    Every read opens the current path so edits made outside the application take
    effect on the next collection.
    """

    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir).absolute() / "references"
        self.root.mkdir(parents=True, exist_ok=True)

    def validate_path(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or "\x00" in relative:
            raise WorkFLowWeaveError("path_forbidden", "文件路径必须是非空相对路径")
        candidate = Path(relative)
        if candidate.is_absolute() or PureWindowsPath(relative).drive or candidate == Path("."):
            raise WorkFLowWeaveError("path_forbidden", "文件路径必须是引用目录内的相对路径")
        try:
            resolved = (self.root / candidate).resolve(strict=False)
            root = self.root.resolve()
            resolved.relative_to(root)
            if resolved == root:
                raise ValueError("Expected a file below the references directory")
        except (OSError, RuntimeError, ValueError):
            raise WorkFLowWeaveError("path_forbidden", "文件路径不能越出引用目录") from None
        return resolved

    @contextmanager
    def _parent_directory(self, path: Path, *, create: bool = False):
        parts = path.relative_to(self.root.resolve()).parts
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(self.root.resolve(), flags)
        try:
            # Traverse through descriptors so replacing a parent with a symlink
            # after validation cannot redirect a read or write outside the root.
            for part in parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, dir_fd=directory)
                    except FileExistsError:
                        pass
                child = os.open(part, flags, dir_fd=directory)
                os.close(directory)
                directory = child
            yield directory, parts[-1]
        finally:
            os.close(directory)

    def create_text(self, relative: str, content: bytes) -> None:
        path = self.validate_path(relative)
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise WorkFLowWeaveError("invalid_argument", "导入文件不是有效的 UTF-8 文本") from None
        if (self.root / relative).is_symlink():
            raise WorkFLowWeaveError("file_conflict", "目标文件已存在")
        try:
            with self._parent_directory(path, create=True) as (directory, name):
                temporary = f".reference-{uuid4().hex}"
                descriptor = os.open(
                    temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666, dir_fd=directory,
                )
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    # Publish complete bytes without replacing another writer's target.
                    os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                            follow_symlinks=False)
                finally:
                    os.unlink(temporary, dir_fd=directory)
        except FileExistsError:
            raise WorkFLowWeaveError("file_conflict", "目标文件已存在") from None
        except WorkFLowWeaveError:
            raise
        except OSError:
            raise WorkFLowWeaveError("storage_failed", "文件保存失败") from None

    def read_text(self, relative: str) -> str:
        path = self.validate_path(relative)
        try:
            with self._parent_directory(path) as (directory, name):
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory,
                )
                with os.fdopen(descriptor, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise WorkFLowWeaveError("invalid_argument", "引用路径不是普通文件")
                    return stream.read().decode("utf-8")
        except WorkFLowWeaveError:
            raise
        except UnicodeDecodeError:
            raise WorkFLowWeaveError("file_encoding", "引用文件不是有效的 UTF-8 文本") from None
        except FileNotFoundError:
            raise WorkFLowWeaveError("file_missing", "引用文件不存在") from None
        except OSError:
            raise WorkFLowWeaveError("storage_failed", "引用文件无法读取") from None
