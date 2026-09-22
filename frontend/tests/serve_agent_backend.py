"""Ephemeral Agent backend for the browser smoke suite.

The process uses the real FastAPI router, EventLog, checkpoint saver and
WorkspaceBackend.  Only the model lease is replaced with a deterministic local
model so the suite never contacts a configured provider or channel.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import uvicorn
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from logagent.agent.config import AgentConfig
from logagent.agent.service import AgentService
from logagent.interaction.app import create_app
from logagent.models import ComponentHealth, HealthReport


class SmokeModel(BaseChatModel):
    """Local streaming model with a cancellable slow response."""

    @property
    def _llm_type(self) -> str:
        return "logagent-browser-smoke"

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
            await asyncio.sleep(30)
        yield ChatGenerationChunk(message=AIMessageChunk(content="已完成：" + prompt))


class SmokeLifecycle:
    def __init__(self, root: Path):
        self._root = root
        self._agent = AgentService(
            root / "workspace",
            root / "runtime",
            config=AgentConfig(idle_timeout=5),
            model_provider=lambda _session: SmokeModel(),
        )
        self._plugins = SimpleNamespace(
            generation=1,
            collectorRegister=SimpleNamespace(describe=lambda: []),
            channelRegister=SimpleNamespace(describe=lambda: []),
            toolRegister=SimpleNamespace(describe=lambda: [], get=lambda _name: None),
        )
        self._services = SimpleNamespace(agent=self._agent, plugins=self._plugins)

    async def start(self):
        await self._agent.initialize()
        return self._services

    async def shutdown(self):
        await self._agent.close()

    async def update_plugin_setting(self, plugin_id: str, enabled: bool):
        return SimpleNamespace(model_dump=lambda mode="json": {"registered": [], "errors": []})

    async def health(self):
        return HealthReport(
            status="ready",
            accepting_runs=True,
            checked_at=datetime.now(UTC),
            components=[ComponentHealth(component="agent", status="available", required=True)],
        )


with TemporaryDirectory(prefix="logagent-agent-browser-") as temporary:
    lifecycle = SmokeLifecycle(Path(temporary))
    uvicorn.run(create_app(lifecycle), host="127.0.0.1", port=14301)
