"""Durable per-session snapshots of the allowed MCP scope."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from logagent.storage_primitives.atomic import atomic_write_json

_UNAVAILABLE = "原会话 MCP 绑定丢失或损坏；已有分析仍可读取"


class BindingStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def read(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"error": _UNAVAILABLE}
        except (UnicodeError, json.JSONDecodeError):
            return {"error": _UNAVAILABLE}
        if type(value) is not dict:
            return {"error": _UNAVAILABLE}
        return value

    def write(self, session_id: str, binding: dict[str, Any]) -> None:
        if type(binding) is not dict:
            raise TypeError("MCP binding must be a JSON object")
        atomic_write_json(self._path(session_id), binding)

    def _path(self, session_id: str) -> Path:
        if (
            not isinstance(session_id, str)
            or not session_id
            or session_id in {".", ".."}
            or "/" in session_id
            or "\\" in session_id
            or "\x00" in session_id
        ):
            raise ValueError("session_id must be a single path component")
        return self.root / f"{session_id}.json"
