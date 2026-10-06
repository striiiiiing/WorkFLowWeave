"""Lexical path validation and secure temporary-name generation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import uuid4


class StoragePathError(ValueError):
    """A requested storage path is outside its configured root."""


def resolve_under(root: str | Path, relative: str | Path) -> Path:
    """Resolve a relative path under ``root``, including existing symlinks."""
    base = Path(root).resolve()
    requested = Path(relative)
    if requested.is_absolute() or "\x00" in str(relative):
        raise StoragePathError("storage path must be a relative path")
    candidate = (base / requested).resolve()
    if not candidate.is_relative_to(base):
        raise StoragePathError("storage path escapes its root")
    return candidate


def temporary_path(parent: str | Path, *, prefix: str = ".tmp-") -> Path:
    """Create and return a unique, empty temporary file in ``parent``."""
    directory = Path(parent)
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=prefix, dir=directory)
    os.close(fd)
    return Path(name)


def unique_name(prefix: str = ".tmp-") -> str:
    """Return an unpredictable filename component without creating a file."""
    return prefix + uuid4().hex
