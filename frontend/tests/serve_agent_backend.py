"""Ephemeral Agent backend for the browser smoke suite.

The process uses the real application lifecycle, FastAPI router, EventLog and
checkpoint saver. Only the model lease is replaced with a deterministic local
model so the suite never contacts a configured provider.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from shutil import copytree, ignore_patterns
from tempfile import TemporaryDirectory

import uvicorn
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from workflowweave.agent.config import AgentConfig
from workflowweave.interaction.app import create_app
from workflowweave.lifecycle import ApplicationLifecycle
from workflowweave.models import SystemConfig


class SmokeModel(BaseChatModel):
    """Local streaming model with a cancellable slow response."""

    @property
    def _llm_type(self) -> str:
        return "workflowweave-browser-smoke"

    def bind_tools(self, tools, **kwargs):
        return self

    @staticmethod
    def _prompt(messages: list[BaseMessage]) -> str:
        for message in reversed(messages):
            if getattr(message, "type", None) == "human":
                return str(getattr(message, "content", ""))
        return ""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        prompt = self._prompt(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="已完成：" + prompt,
        ))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop, run_manager, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        prompt = self._prompt(messages)
        if "slow" in prompt:
            await asyncio.sleep(120)
        yield ChatGenerationChunk(message=AIMessageChunk(content="已完成：" + prompt))


class SmokeLifecycle(ApplicationLifecycle):
    def __init__(self, root: Path):
        copytree(Path(__file__).resolve().parents[2] / "plugins", root / "plugins",
                 ignore=ignore_patterns("__pycache__", "*.pyc", "config.json"))
        super().__init__(
            SystemConfig(
                data_dir=str(root / "data"),
                plugin_dir=str(root / "plugins"),
                master_key_file=str(root / "master.key"),
                host="127.0.0.1",
                port=14301,
            ),
            channel_factories={},
        )

    async def start(self):
        services = await super().start()
        services.agent.model_provider = lambda _session: SmokeModel()
        services.agent.config = AgentConfig(idle_timeout=60)
        return services


with TemporaryDirectory(prefix="workflowweave-agent-browser-") as temporary:
    lifecycle = SmokeLifecycle(Path(temporary))
    uvicorn.run(create_app(lifecycle), host="127.0.0.1", port=14301)
