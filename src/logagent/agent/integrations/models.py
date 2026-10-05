"""Lease already selected models through the shared application AI service."""
from __future__ import annotations

import inspect
from contextlib import asynccontextmanager

from logagent.agent.contracts import SessionView
from logagent.errors import LogAgentError


class ModelProvider:
    def __init__(self, *, provider=None, ai_service=None, ai_config=None):
        self.model_provider = provider
        self.ai_service = ai_service
        self.ai_config = ai_config

    @asynccontextmanager
    async def lease(self, session: SessionView, *, output_tokens: int,
                     ai_config=None, model: str | None = None):
        if self.model_provider is not None:
            value = self.model_provider(session)
            if inspect.isawaitable(value):
                value = await value
            if hasattr(value, "__aenter__"):
                async with value as model:
                    yield model
            else:
                yield value
            return
        ai_config = self.ai_config if ai_config is None else ai_config
        model = session.model if model is None else model
        if self.ai_service is None or ai_config is None or model is None:
            raise LogAgentError("model_unavailable", "Agent session 没有可用模型")
        async with self.ai_service.lease(
            ai_config, model=model, streaming=True,
            max_output_tokens=output_tokens,
        ) as model:
            yield model

