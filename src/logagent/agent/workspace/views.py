"""Read-only logical runtime views exposed through the workspace file API."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from logagent.errors import LogAgentError
from logagent.storage_primitives.digest import sha256_bytes

if TYPE_CHECKING:
    from logagent.agent.contracts import RuntimeIdentity


class RuntimeSelfView:
    def __init__(self, identity: RuntimeIdentity | None):
        self.identity = identity

    def read(self, path: str, *, offset: int, limit: int, output_bytes: int) -> dict[str, Any]:
        if self.identity is None:
            raise LogAgentError("runtime_identity_unavailable", "当前工作区没有绑定 Agent 会话")
        content = (json.dumps(self.identity.document(), ensure_ascii=False, indent=2) + "\n").encode()
        lines = content.decode("utf-8").splitlines(keepends=True)
        selected = lines[offset:offset + limit]
        if sum(map(len, selected)) > output_bytes:
            raise LogAgentError("output_limit_exceeded", "Runtime/self.json 超过读取预算")
        end = offset + len(selected)
        return {
            "status": "success",
            "kind": "file",
            "path": path,
            "content": "".join(selected),
            "hash": sha256_bytes(content),
            "offset": offset,
            "next_offset": end if end < len(lines) else None,
            "total_lines": len(lines),
            "readonly": True,
        }
