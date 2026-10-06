"""Atomic persistence for the single Agent configuration document."""

from __future__ import annotations

from pathlib import Path

from workflowweave.agent.config import AgentConfig
from workflowweave.storage_primitives.atomic import atomic_write_bytes


class SettingsStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self, config: AgentConfig) -> AgentConfig:
        try:
            payload = self.path.read_bytes()
        except FileNotFoundError:
            return config.model_copy(deep=True)
        return AgentConfig.model_validate_json(payload)

    def save(self, config: AgentConfig) -> None:
        payload = config.model_dump_json(indent=2).encode("utf-8")
        atomic_write_bytes(self.path, payload)
