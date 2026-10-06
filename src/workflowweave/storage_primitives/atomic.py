"""Durable same-directory file replacement helpers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_bytes(path: str | Path, content: bytes, *, mode: int = 0o600) -> None:
    """Replace ``path`` only after its complete contents have reached disk."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}-", dir=target.parent)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            os.unlink(temporary)


def atomic_write_text(
    path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
    mode: int = 0o600,
) -> None:
    atomic_write_bytes(path, content.encode(encoding), mode=mode)


def atomic_write_json(
    path: str | Path,
    value: Any,
    *,
    mode: int = 0o600,
    indent: int | None = None,
    sort_keys: bool = False,
) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=indent,
        sort_keys=sort_keys,
        separators=None if indent is not None else (",", ":"),
    )
    atomic_write_text(path, payload, mode=mode)
