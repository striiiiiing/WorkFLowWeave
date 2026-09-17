"""Turn shared channel configuration into a LangChain chat model."""

from __future__ import annotations

from copy import deepcopy
from typing import Protocol

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from openai import Omit

from logagent.models import AIConfig


class ModelFactory(Protocol):
    def create(
        self, config: AIConfig, *, model: str, credential: str | None,
    ) -> BaseChatModel: ...

    async def close(self) -> None: ...


class OpenAIModelFactory:
    """Own transport connections, without caching conversations or model results."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client if client is not None else httpx.AsyncClient(timeout=None)
        self._owned = client is None

    def create(self, config: AIConfig, *, model: str, credential: str | None) -> BaseChatModel:
        # A supplier avoids both ambient API-key fallback and an unused sync client.
        async def api_key() -> str:
            return credential if credential is not None else ""

        # Local compatible services may omit authentication; use the SDK omission marker.
        return ChatOpenAI(
            model=model, base_url=config.base_url, api_key=api_key,
            http_async_client=self.client, openai_proxy=None, http_socket_options=(),
            model_kwargs={"extra_headers": {"Authorization": Omit()}} if credential is None else {},
            timeout=None, max_retries=0, cache=False,
            streaming=False, disable_streaming=True, use_responses_api=False,
            extra_body=deepcopy(config.models[model]),
        )

    async def close(self) -> None:
        if self._owned:
            await self.client.aclose()
