"""Stateless one-shot AI execution with mock and OpenAI-compatible providers."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from logagent.errors import LogAgentError, exception_error
from logagent.models import AIConfig, AnalysisResult, ErrorInfo, ExecutionContext


class ProviderError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False, uncertain: bool = False):
        super().__init__(message)
        self.code, self.retryable, self.uncertain = code, retryable, uncertain


class Provider(Protocol):
    async def complete(self, config: AIConfig, *, system: str, user: str, credential: str | None = None) -> Mapping[str, Any]: ...
    async def close(self) -> None: ...


def _prompt(prompt: str, input_text: str) -> str:
    return prompt.replace("{input}", input_text) if "{input}" in prompt else f"{prompt}\n\n{input_text}"


class MockProvider:
    def __init__(self, responder: Callable[..., Any] | None = None):
        self.responder = responder

    async def complete(self, config: AIConfig, *, system: str, user: str, credential: str | None = None) -> Mapping[str, Any]:
        if self.responder is None:
            return {"text": user}
        value = self.responder(config=config, system=system, user=user, credential=credential)
        return await value if inspect.isawaitable(value) else value

    async def close(self) -> None:
        return None


class HTTPProvider:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient()
        self._owned = client is None

    async def complete(self, config: AIConfig, *, system: str, user: str, credential: str | None = None) -> Mapping[str, Any]:
        if not config.base_url:
            raise ProviderError("invalid_config", "HTTP provider 需要 base_url")
        headers = {"content-type": "application/json"}
        if credential:
            headers["authorization"] = f"Bearer {credential}"
        payload = {"model": config.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], **dict(config.model_options)}
        try:
            response = await self.client.post(config.base_url.rstrip("/") + "/chat/completions", headers=headers, json=payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ProviderError("network_error", "模型服务连接失败", retryable=True) from exc
        if response.status_code in (401, 403):
            raise ProviderError("authentication_failed", "模型服务认证失败")
        if response.status_code >= 500 or response.status_code == 429:
            raise ProviderError("provider_unavailable", "模型服务暂时不可用", retryable=True)
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderError("provider_rejected", "模型服务拒绝请求")
        try:
            data = response.json()
        except Exception as exc:
            raise ProviderError("invalid_response", "模型服务返回的 JSON 无效") from exc
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("invalid_response", "模型服务响应缺少有效文本") from None
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("invalid_response", "模型服务响应缺少有效文本")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return {"text": text, "usage": usage}

    async def close(self) -> None:
        if self._owned:
            await self.client.aclose()


class AIService:
    def __init__(self, *, providers: Mapping[str, Provider] | None = None, credential_resolver: Any = None):
        self.providers = dict(providers or {"mock": MockProvider(), "http": HTTPProvider()})
        self.credential_resolver = credential_resolver

    def validate(self, config: AIConfig) -> None:
        if config.provider not in {"mock", "http"}:
            raise LogAgentError("invalid_config", "不支持的 AI provider", {"field": "provider"})
        if config.provider == "http":
            parsed = urlparse(config.base_url or "")
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise LogAgentError("invalid_config", "HTTP provider 的 base_url 无效", {"field": "base_url"})
        forbidden = {"temperature", "top_k", "messages", "model", "api_key", "base_url", "timeout", "retries"}
        bad = sorted(forbidden & set(config.model_options))
        if bad:
            raise LogAgentError("invalid_config", "model_options 包含不允许覆盖的字段", {"fields": bad})
        unknown = set(config.model_options) - {"enable_thinking", "thinking", "thinking_level", "response_format"}
        if unknown:
            raise LogAgentError("invalid_config", "model_options 包含未声明字段", {"fields": sorted(unknown)})

    async def execute(self, config: AIConfig, prompt: str, input_text: str, *, task_id: str = "task", context: ExecutionContext | None = None) -> AnalysisResult:
        started = time.perf_counter()
        try:
            self.validate(config)
        except LogAgentError as exc:
            return AnalysisResult(task_id=task_id, status="failed", error=exc.info, elapsed_ms=(time.perf_counter()-started)*1000)
        provider = self.providers.get(config.provider)
        if provider is None:
            return AnalysisResult(task_id=task_id, status="failed", error=ErrorInfo(code="provider_missing", message="AI provider 不可用"), elapsed_ms=(time.perf_counter()-started)*1000)
        credential = None
        try:
            if config.api_key is not None and self.credential_resolver is not None:
                credential = await self.credential_resolver.resolve(config.api_key)
            system, user = config.system_prompt, _prompt(prompt, input_text)
            deadline = started + config.timeout
            last: ProviderError | None = None
            for attempt in range(config.retries + 1):
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise TimeoutError
                try:
                    data = await asyncio.wait_for(provider.complete(config, system=system, user=user, credential=credential), remaining)
                    text = data.get("text") if isinstance(data, Mapping) else None
                    if not isinstance(text, str) or not text.strip():
                        raise ProviderError("invalid_response", "模型服务响应缺少有效文本")
                    usage = data.get("usage", {}) if isinstance(data, Mapping) and isinstance(data.get("usage", {}), dict) else {}
                    return AnalysisResult(task_id=task_id, status="success", text=text, usage=usage, elapsed_ms=(time.perf_counter()-started)*1000)
                except ProviderError as exc:
                    last = exc
                    if not exc.retryable or attempt >= config.retries:
                        break
                    await asyncio.sleep(min(0.25 * (2 ** attempt), max(0, deadline-time.perf_counter())))
            if last is None:
                raise TimeoutError
            return AnalysisResult(task_id=task_id, status="failed", error=ErrorInfo(code=last.code, message=last.args[0]), elapsed_ms=(time.perf_counter()-started)*1000)
        except TimeoutError:
            return AnalysisResult(task_id=task_id, status="timeout", error=ErrorInfo(code="ai_timeout", message="AI 调用超时"), elapsed_ms=(time.perf_counter()-started)*1000)
        except asyncio.CancelledError:
            return AnalysisResult(task_id=task_id, status="cancelled", error=ErrorInfo(code="ai_cancelled", message="AI 调用已取消"), elapsed_ms=(time.perf_counter()-started)*1000)
        except Exception as exc:
            return AnalysisResult(task_id=task_id, status="failed", error=exception_error(exc, code="ai_failed", message="AI 调用失败"), elapsed_ms=(time.perf_counter()-started)*1000)

    async def close(self) -> None:
        for provider in self.providers.values():
            close = getattr(provider, "close", None)
            if close:
                value = close()
                if inspect.isawaitable(value):
                    await value
