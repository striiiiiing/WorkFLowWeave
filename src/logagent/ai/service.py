"""One-shot analysis with explicit model selection and a single request budget."""

from __future__ import annotations

import asyncio
import inspect
import math
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from logagent.errors import LogAgentError, exception_error, validation_error
from logagent.models import AIConfig, AnalysisResult, ErrorInfo, ExecutionContext, copy_model

# Provider extensions cannot replace service-owned request or connection settings.
_MANAGED_OPTIONS = frozenset({
    "temperature", "top_k", "model", "messages", "api_key", "base_url", "timeout",
    "retries", "max_retries", "stream", "stream_options", "headers", "extra_headers",
    "authorization", "auth", "http_client", "extra_body", "extra_query",
})
_RETRY_DELAY = 0.25
_CLOSE_TIMEOUT = 5.0  # Local client cleanup only; separate from paid request budgets.


class ProviderError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False, uncertain: bool = False):
        super().__init__(message)
        self.code, self.retryable, self.uncertain = code, retryable, uncertain


class Provider(Protocol):
    async def complete(
        self, config: AIConfig, *, model: str, system: str, user: str,
        credential: str | None = None,
    ) -> Mapping[str, Any]: ...

    async def close(self) -> None: ...


def _prompt(prompt: str, input_text: str) -> str:
    return prompt.replace("{input}", input_text) if "{input}" in prompt else f"{prompt}\n\n{input_text}"


def _check_cancelled() -> None:
    if asyncio.current_task().cancelling():
        raise asyncio.CancelledError


class MockProvider:
    def __init__(self, responder: Callable[..., Any] | None = None):
        self.responder = responder

    async def complete(self, config, *, model, system, user, credential=None):
        if self.responder is None:
            return {"text": user}
        value = self.responder(
            config=config, model=model, system=system, user=user, credential=credential,
        )
        return await value if inspect.isawaitable(value) else value

    async def close(self) -> None:
        pass


class HTTPProvider:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client if client is not None else httpx.AsyncClient(timeout=None)
        self._owned = client is None

    async def complete(self, config, *, model, system, user, credential=None):
        headers = {"content-type": "application/json"}
        if credential is not None:
            headers["authorization"] = f"Bearer {credential}"
        payload = {
            **config.models[model], "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            response = await self.client.post(
                config.base_url.rstrip("/") + "/chat/completions",
                headers=headers, json=payload, timeout=None,
            )
        except (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError) as exc:
            raise ProviderError("network_error", "模型服务连接失败", retryable=True) from exc
        except httpx.HTTPError as exc:
            # Bytes may already have reached the server: repeating could incur another charge.
            raise ProviderError("network_error", "模型请求受理状态不确定", uncertain=True) from exc
        if response.status_code in (401, 403):
            raise ProviderError("authentication_failed", "模型服务认证失败")
        if response.status_code == 429:
            raise ProviderError("rate_limited", "模型服务限流", retryable=True)
        if response.status_code >= 500:
            raise ProviderError("provider_unavailable", "模型请求受理状态不确定", uncertain=True)
        if not 200 <= response.status_code < 300:
            raise ProviderError("provider_rejected", "模型服务拒绝请求")
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            if "error" in data:
                raise ValueError("Error response")
            return {"text": text, "usage": data.get("usage", {})}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("invalid_response", "模型服务响应结构无效") from exc

    async def close(self) -> None:
        if self._owned:
            await self.client.aclose()


class AIService:
    def __init__(
        self, *, providers: Mapping[str, Provider] | None = None,
        credential_resolver: Any = None, close_timeout: float = _CLOSE_TIMEOUT,
    ):
        if not math.isfinite(close_timeout) or close_timeout <= 0:
            raise ValueError("close_timeout must be positive and finite")
        self.providers = dict(providers) if providers is not None else {
            "mock": MockProvider(), "http": HTTPProvider(),
        }
        self.credential_resolver = credential_resolver
        self._close_timeout = close_timeout
        self._close_task: asyncio.Task | None = None

    def validate(self, config: AIConfig, model: str | None = None) -> None:
        try:
            config = copy_model(config)
        except ValidationError as exc:
            raise validation_error(exc) from None
        if config.provider not in self.providers:
            raise LogAgentError("provider_missing", "AI provider 不可用", {"field": "provider"})
        if config.provider == "http":
            parsed = urlparse(config.base_url or "")
            if (
                parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
            ):
                raise LogAgentError("invalid_config", "HTTP base_url 无效", {"field": "base_url"})
        if model is not None and model not in config.models:
            raise LogAgentError("invalid_config", "选择的 AI model 不存在", {"field": "model"})
        for options in config.models.values():
            bad = sorted(_MANAGED_OPTIONS & options.keys())
            if bad:
                raise LogAgentError("invalid_config", "模型参数覆盖管理字段", {"fields": bad})

    async def execute(
        self, config: AIConfig, prompt: str, input_text: str, *, model: str,
        task_id: str = "task", context: ExecutionContext | None = None,
    ) -> AnalysisResult:
        started = time.perf_counter()
        try:
            _check_cancelled()
            if self._close_task is not None:
                raise LogAgentError("ai_closed", "AI 服务已关闭")
            config = copy_model(config)
            self.validate(config, model)
            async with asyncio.timeout(config.timeout):
                credential = None
                if config.api_key is not None:
                    if self.credential_resolver is None:
                        raise LogAgentError("credential_resolver_missing", "AI 凭据解析器未配置")
                    credential = await self.credential_resolver.resolve(config.api_key)
                    if not isinstance(credential, str) or not credential:
                        raise LogAgentError("credential_invalid", "AI 凭据解析结果无效")
                result = await self._request(
                    config, model, _prompt(prompt, input_text), credential, task_id,
                )
            return result.model_copy(update={"elapsed_ms": (time.perf_counter() - started) * 1000})
        except asyncio.CancelledError:
            status, error = "cancelled", ErrorInfo(code="ai_cancelled", message="AI 调用已取消")
        except TimeoutError:
            status, error = "timeout", ErrorInfo(code="ai_timeout", message="AI 调用总时限已耗尽")
        except ValidationError:
            status, error = "failed", ErrorInfo(code="invalid_config", message="AI 配置无效")
        except LogAgentError as exc:
            # A resolver is injectable; its arbitrary message/details may contain credentials.
            status, error = "failed", ErrorInfo(code=exc.code, message="AI 配置或凭据不可用")
        except ProviderError as exc:
            status, error = "failed", ErrorInfo(
                code=exc.code, message="AI 模型调用失败",
                details={"uncertain": exc.uncertain},
            )
        except Exception as exc:
            status, error = "failed", exception_error(exc, code="ai_failed", message="AI 调用失败")
        return AnalysisResult(
            task_id=task_id, status=status, error=error,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    async def _request(self, config, model, user, credential, task_id):
        provider = self.providers[config.provider]
        for attempt in range(config.retries + 1):
            _check_cancelled()
            try:
                data = await provider.complete(
                    copy_model(config), model=model, system=config.system_prompt,
                    user=user, credential=credential,
                )
                _check_cancelled()
                try:
                    if not isinstance(data, Mapping) or "error" in data:
                        raise ValueError("Invalid provider result")
                    return AnalysisResult(
                        task_id=task_id, status="success",
                        text=data.get("text"), usage=data.get("usage", {}),
                    )
                except (ValueError, TypeError) as exc:
                    raise ProviderError("invalid_response", "模型服务响应结构无效") from exc
            except ProviderError as exc:
                if not exc.retryable or exc.uncertain or attempt == config.retries:
                    raise
                _check_cancelled()
                await asyncio.sleep(_RETRY_DELAY * 2 ** min(attempt, 5))
        raise AssertionError("Unreachable retry state")

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_providers())
        await asyncio.shield(self._close_task)

    async def _close_providers(self) -> None:
        async def close_one(provider):
            try:
                async with asyncio.timeout(self._close_timeout):
                    await provider.close()
            except Exception as exc:
                return type(exc).__name__
            return None

        # An adapter can be registered under several names but is still owned once.
        providers = {id(provider): provider for provider in self.providers.values()}
        failures = await asyncio.gather(*(close_one(provider) for provider in providers.values()))
        if any(failures):
            raise LogAgentError(
                "ai_cleanup_failed", "AI 客户端清理失败",
                {"failures": [failure for failure in failures if failure]},
            )
