"""Persist the frozen AI invocation configuration for Workflow-owned sessions."""

from pathlib import Path

from workflowweave.models import AIConfig
from workflowweave.storage_primitives.atomic import atomic_write_json
from workflowweave.storage_primitives.paths import resolve_under


class InvocationStore:
    def __init__(self, root: Path):
        self.root = root

    def read(self, session_id: str) -> AIConfig:
        return AIConfig.model_validate_json(self._path(session_id).read_text())

    def write(self, session_id: str, config: AIConfig) -> None:
        atomic_write_json(self._path(session_id), config.model_dump(mode="json"))

    def _path(self, session_id: str) -> Path:
        if not session_id or session_id in {".", ".."} or "/" in session_id or "\\" in session_id:
            raise ValueError("session_id must be a single path component")
        return resolve_under(self.root, f"{session_id}.json")
