"""One-shot analysis with explicit model selection and a single request budget."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from openai import APIConnectionError, APIError, APIStatusError
from pydantic import ValidationError

from logagent.ai.models import ModelFactory
from logagent.errors import LogAgentError, exception_error, validation_error
from logagent.models import AIConfig, AnalysisResult, ErrorInfo, ExecutionContext, copy_model

# Model extensions cannot replace service-owned request or connection settings.
_MANAGED_OPTIONS = frozenset({
    "temperature", "top_k", "model", "messages", "api_key", "base_url", "timeout",
    "retries", "max_retries", "stream", "stream_options", "headers", "extra_headers",
    "authorization", "auth", "http_client", "extra_body", "extra_query",
})
_RETRY_DELAY = 0.25
_CLOSE_TIMEOUT = 5.0  # Local client cleanup only; separate from paid request budgets.
_LOGGER = logging.getLogger(__name__)


class ModelError(Exception):
    def __init__(
        self, code: str, message: str, *, retryable: bool = False,
        uncertain: bool = False, status_code: int | None = None,
    ):
        super().__init__(message)
        self.code, self.retryable, self.uncertain = code, retryable, uncertain
        self.status_code = status_code


def _prompt(prompt: str, input_text: str) -> str:
    return prompt.replace("{input}", input_text) if "{input}" in prompt else f"{prompt}\n\n{input_text}"


def _check_cancelled() -> None:
    if asyncio.current_task().cancelling():
        raise asyncio.CancelledError


async def _invoke(model: BaseChatModel, messages) -> AIMessage:
    try:
        return await model.ainvoke([message.model_copy(deep=True) for message in messages])
    except APIStatusError as exc:
        status = exc.status_code
        code = {
            401: "authentication_failed", 403: "authentication_failed",
            408: "provider_timeout", 429: "rate_limited",
        }.get(status, "provider_unavailable" if 500 <= status < 600 else "provider_rejected")
        raise ModelError(
            code, "模型服务返回错误状态", status_code=status,
            retryable=status in (408, 429) or 500 <= status < 600,
        ) from exc
    except APIConnectionError as exc:
        cause = exc.__cause__
        # LangChain normalizes SDK exceptions, retaining the transport cause underneath.
        while isinstance(cause, APIConnectionError):
            cause = cause.__cause__
        unaccepted = isinstance(
            cause, (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError),
        )
        raise ModelError(
            "network_error", "模型服务连接失败", retryable=unaccepted,
            uncertain=not unaccepted,
        ) from exc
    except (APIError, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ModelError("invalid_response", "模型服务响应结构无效") from exc


def _analysis_result(message: AIMessage, task_id: str) -> AnalysisResult:
    if not isinstance(message, AIMessage) or not isinstance(message.content, str):
        raise ModelError("invalid_response", "模型服务必须返回文本消息")
    if message.additional_kwargs.get("refusal") or message.response_metadata.get("error"):
        raise ModelError("provider_rejected", "模型服务拒绝生成结果")
    if message.tool_calls or message.invalid_tool_calls or message.additional_kwargs.get("tool_calls"):
        raise ModelError("invalid_response", "单次分析不能执行工具调用")
    usage = message.response_metadata.get("token_usage", message.usage_metadata)
    try:
        return AnalysisResult(
            task_id=task_id, status="success", text=message.content,
            usage={} if usage is None else usage,
        )
    except (ValueError, TypeError) as exc:
        raise ModelError("invalid_response", "模型服务响应结构无效") from exc


class AIService:
    def __init__(
        self, *, model_factories: Mapping[str, ModelFactory],
        credential_resolver: Any = None, close_timeout: float = _CLOSE_TIMEOUT,
    ):
        if not math.isfinite(close_timeout) or close_timeout <= 0:
            raise ValueError("close_timeout must be positive and finite")
        self.model_factories = dict(model_factories)
        self.credential_resolver = credential_resolver
        self._close_timeout = close_timeout
        self._close_task: asyncio.Task | None = None

    def validate(self, config: AIConfig, model: str | None = None) -> None:
        try:
            config = copy_model(config)
        except ValidationError as exc:
            raise validation_error(exc) from None
        if config.provider not in self.model_factories:
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
                    config, model, _prompt(prompt, input_text), credential, task_id, context,
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
        except ModelError as exc:
            status, error = "failed", ErrorInfo(
                code=exc.code, message="AI 模型调用失败",
                details={"uncertain": exc.uncertain, "status_code": exc.status_code},
            )
        except Exception as exc:
            status, error = "failed", exception_error(exc, code="ai_failed", message="AI 调用失败")
        _LOGGER.warning(
            "ai_call_failed",
            extra={
                "event": "ai_call_failed", "task_id": task_id, "status": status,
                "error_code": error.code,
                "workflow_id": context.workflow_id if context else None,
                "session_id": context.session_id if context else None,
            },
        )
        return AnalysisResult(
            task_id=task_id, status=status, error=error,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    async def _request(self, config, model, user, credential, task_id, context):
        factory = self.model_factories[config.provider]
        messages = [SystemMessage(content=config.system_prompt), HumanMessage(content=user)]
        for attempt in range(config.retries + 1):
            _check_cancelled()
            try:
                chat_model = factory.create(copy_model(config), model=model, credential=credential)
                message = await _invoke(chat_model, messages)
                _check_cancelled()
                return _analysis_result(message, task_id)
            except ModelError as exc:
                retry = exc.retryable and not exc.uncertain and attempt < config.retries
                _LOGGER.warning(
                    "ai_attempt_failed",
                    extra={
                        "event": "ai_attempt_failed", "task_id": task_id,
                        "error_code": exc.code, "status_code": exc.status_code,
                        "attempt": attempt + 1, "will_retry": retry,
                        "uncertain": exc.uncertain,
                        "workflow_id": context.workflow_id if context else None,
                        "session_id": context.session_id if context else None,
                    },
                )
                if not retry:
                    raise
                _check_cancelled()
                await asyncio.sleep(_RETRY_DELAY * 2 ** min(attempt, 5))
        raise AssertionError("Unreachable retry state")

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_models())
        await asyncio.shield(self._close_task)

    async def _close_models(self) -> None:
        async def close_one(factory):
            try:
                async with asyncio.timeout(self._close_timeout):
                    await factory.close()
            except Exception as exc:
                return type(exc).__name__
            return None

        # A factory can be registered under several names but is still owned once.
        factories = {id(factory): factory for factory in self.model_factories.values()}
        failures = await asyncio.gather(*(close_one(factory) for factory in factories.values()))
        if any(failures):
            raise LogAgentError(
                "ai_cleanup_failed", "AI 客户端清理失败",
                {"failures": [failure for failure in failures if failure]},
            )
