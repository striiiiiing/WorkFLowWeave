"""向 Workflow 提供异步单次分析，统一请求预算、重试与取消通知。"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import ValidationError

from workflowweave.ai.channels import ChannelFactory
from workflowweave.ai.errors import ModelError, error_info, model_error
from workflowweave.ai.manager import ChannelManager
from workflowweave.ai.options import validate_config
from workflowweave.ai.prompts import build_messages
from workflowweave.errors import WorkFLowWeaveError, validation_error
from workflowweave.models import (
    AIConfig,
    AnalysisResult,
    Credential,
    ErrorInfo,
    ExecutionContext,
    copy_model,
)

_RETRY_DELAY = 0.25
_CLOSE_TIMEOUT = 5.0
_LOGGER = logging.getLogger(__name__)


class CredentialResolver(Protocol):
    """将配置中的凭据引用异步解析为明文的注入协议。"""

    async def resolve(self, credential: Credential) -> str:
        """解析一个凭据引用；解析失败由实现抛出异常，不能返回伪造凭据。"""
        ...


@dataclass(frozen=True)
class CancellationNotice:
    """取消确认时交给同步回调的通知信封。

    包含渠道配置 ID、模型名、分析任务 ID 和可选执行上下文；不包含输入或凭据。
    数据类字段不可重新赋值，context 仍是调用方传入的上下文对象。
    """

    channel_id: str
    model: str
    task_id: str
    context: ExecutionContext | None


def _check_cancelled() -> None:
    """检查当前任务的取消计数，防止下游吞掉取消后仍返回成功或继续重试。"""
    if asyncio.current_task().cancelling():
        raise asyncio.CancelledError


def _result(message: AIMessage, task_id: str) -> AnalysisResult:
    """把单条文本 AIMessage 转为成功分析结果，并保留可用 token usage。

    拒绝生成、错误元数据、工具调用或非文本消息不能当作成功结果。空白正文
    及非法 usage 由 AnalysisResult 数据校验拒绝，异常交给调用层统一处理。
    """
    if not isinstance(message, AIMessage) or not isinstance(message.content, str):
        raise ModelError("invalid_response", "模型服务必须返回文本消息")
    if message.additional_kwargs.get("refusal") or message.response_metadata.get("error"):
        raise ModelError("provider_rejected", "模型服务拒绝生成结果",
                         response_body=message.model_dump_json())
    if message.tool_calls or message.invalid_tool_calls or message.additional_kwargs.get("tool_calls"):
        raise ModelError("invalid_response", "单次分析不能执行工具调用",
                         response_body=message.model_dump_json())
    usage = message.response_metadata.get("token_usage", message.usage_metadata)
    return AnalysisResult(task_id=task_id, status="success", text=message.content,
                          usage={} if usage is None else usage)


class AIService:
    """组合渠道、凭据、提示词与模型调用的无会话分析服务。

    服务只保留渠道资源，不保存对话或分析结果。依赖通过工厂和凭据协议注入，
    Workflow 负责分析分支、汇总与结果持久化。
    """

    def __init__(
        self, *, channel_factories: Mapping[str, ChannelFactory],
        credential_resolver: CredentialResolver | None = None,
        close_timeout: float = _CLOSE_TIMEOUT,
    ):
        """建立服务依赖及渠道管理器。

        Args:
            channel_factories: 渠道类型到工厂的映射；正式装配注册 http 类型。
            credential_resolver: 可选凭据解析器；配置引用凭据时必须提供。
            close_timeout: 每个渠道清理预算，单位秒，与模型请求预算分开。

        Raises:
            ValueError: 清理预算不是有限正数。
        """
        if not math.isfinite(close_timeout) or close_timeout <= 0:
            raise ValueError("close_timeout must be positive and finite")
        self.channels = ChannelManager(channel_factories, close_timeout)
        self.credential_resolver = credential_resolver

    def validate(self, config: AIConfig, model: str | None = None) -> None:
        """重新校验配置副本及全部模型参数，不解析凭据或访问网络。

        传入 model 时同时检查显式模型选择；校验失败统一抛出 WorkFLowWeaveError。
        """
        try:
            validate_config(copy_model(config), self.channels.factories, model)
        except ValidationError as exc:
            raise validation_error(exc) from None

    @staticmethod
    def input_counter(config, model):
        import tiktoken
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError as exc:
            raise WorkFLowWeaveError("tokenizer_unavailable", "模型没有已知的精确 tokenizer",
                                {"model": model, "ai": config.id}) from exc
        return lambda text: len(encoding.encode(text, disallowed_special=()))

    async def _credential(self, config: AIConfig) -> str | None:
        """解析本次配置的凭据；未配置认证时返回 None，不读取环境默认密钥。

        配置了凭据引用却没有解析器，或解析结果不是非空字符串时明确失败。
        """
        if config.api_key is None:
            return None
        if self.credential_resolver is None:
            raise WorkFLowWeaveError("credential_resolver_missing", "AI 凭据解析器未配置")
        credential = await self.credential_resolver.resolve(config.api_key)
        if not isinstance(credential, str) or not credential:
            raise WorkFLowWeaveError("credential_invalid", "AI 凭据解析结果无效")
        return credential

    @asynccontextmanager
    async def _model_lease(self, config, *, model, streaming, max_output_tokens):
        config = copy_model(config)
        self.validate(config, model)
        async with self.channels.lease(config) as channel:
            credential = await self._credential(config)
            try:
                chat = channel.create_model(
                    config, model=model, credential=credential,
                    streaming=streaming, max_output_tokens=max_output_tokens,
                )
            except Exception as exc:
                error = model_error(exc)
                error.report = error_info(exc, credential=credential)
                raise error from None
            yield chat, credential

    @asynccontextmanager
    async def lease(
        self, config: AIConfig, *, model: str, streaming: bool = False,
        max_output_tokens: int | None = None,
    ):
        """借用模型直到退出上下文；调用方管理每次请求预算和流式重试。

        连接关闭会取消当前借用任务。工具或文件异常不被归类成模型失败。
        上游模型错误的凭据脱敏由这一共享边界执行。
        """
        from httpx import HTTPError
        from openai import OpenAIError

        async with self._model_lease(
            config, model=model, streaming=streaming, max_output_tokens=max_output_tokens,
        ) as (chat, credential):
            try:
                yield chat
            except (ModelError, HTTPError, OpenAIError) as exc:
                error = model_error(exc)
                error.report = error_info(exc, credential=credential)
                raise error from None

    async def start_channel(self, config: AIConfig) -> None:
        """在配置的总预算内显式启动或重新打开渠道，不执行远端模型发现。"""
        config = copy_model(config)
        self.validate(config)
        async with asyncio.timeout(config.timeout):
            await self.channels.start(config)

    async def close_channel(self, config: AIConfig) -> None:
        """校验配置后关闭对应连接，取消其活动调用；再次使用须显式启动。"""
        self.validate(config)
        await self.channels.stop(copy_model(config))

    async def list_models(self, config: AIConfig) -> list[str]:
        """使用渠道凭据查询上游模型 ID，不改写 config.models。

        模型发现、凭据解析和重试共用 config.timeout；失败以带完整诊断的
        WorkFLowWeaveError 报告，超时使用 ai_timeout。调用者取消保持协程取消语义。
        """
        config = copy_model(config)
        self.validate(config)

        async def discover():
            """在独立任务中借用渠道，使渠道关闭能够取消模型发现操作。"""
            credential = None
            try:
                async with asyncio.timeout(config.timeout), self.channels.lease(config) as channel:
                    credential = await self._credential(config)
                    return await self._retry(
                        lambda: channel.list_models(credential), config,
                        credential=credential, task_id="models", context=None,
                    )
            except ModelError as exc:
                raise WorkFLowWeaveError(exc.code, str(exc), (exc.report or error_info(exc)).details) from None
            except TimeoutError:
                raise WorkFLowWeaveError("ai_timeout", "模型发现总时限已耗尽") from None

        return await asyncio.create_task(discover())

    async def execute(
        self, config: AIConfig, prompt: str, input_text: str, *, model: str,
        task_id: str = "task", context: ExecutionContext | None = None,
        on_cancel: Callable[[CancellationNotice], None] | None = None,
        system_prompt: str | None = None, user_prompt: str = "",
        messages: list[BaseMessage] | None = None,
    ) -> AnalysisResult:
        """执行一次显式模型分析，返回成功、失败、超时或取消结果。

        Args:
            config: 渠道和模型参数配置；执行使用经过校验的深拷贝。
            prompt: 任务提示词，支持字面占位符 {input}。
            input_text: 本次完整输入，不保存为对话历史。
            model: 必须存在于 config.models 的模型 ID。
            task_id: 分析结果及诊断日志的关联标识。
            context: 可选 Workflow/session 上下文，用于日志和取消通知。
            on_cancel: 可选同步回调，取消确认后调用一次；回调异常记录到取消结果。
            messages: 显式请求消息；用于汇总复用分析前缀，仍共用校验、预算和重试。

        Returns:
            AnalysisResult，包含状态、成功正文或结构化错误，以及总耗时。模型调用
            的取消转为 cancelled 结果；凭据、请求和退避共享 config.timeout。
        """
        started = time.perf_counter()
        try:
            _check_cancelled()
            config = copy_model(config)
            self.validate(config, model)
            if messages is not None and not messages:
                raise ValueError("AI request messages cannot be empty")
            request_messages = messages if messages is not None else build_messages(
                config.system_prompt if system_prompt is None else system_prompt,
                prompt, input_text, user_prompt=user_prompt,
            )
            result = await asyncio.create_task(
                self._execute(config, model, request_messages, task_id, context)
            )
            _check_cancelled()
            return result.model_copy(update={"elapsed_ms": (time.perf_counter() - started) * 1000})
        except asyncio.CancelledError:
            status, error = "cancelled", ErrorInfo(code="ai_cancelled", message="AI 调用已取消")
            if on_cancel is not None:
                try:
                    on_cancel(CancellationNotice(config.id, model, task_id, context))
                except Exception as exc:
                    error.details["notification_error"] = error_info(exc).model_dump(mode="json")
        except TimeoutError:
            status, error = "timeout", ErrorInfo(code="ai_timeout", message="AI 调用总时限已耗尽")
        except ValidationError as exc:
            status, error = "failed", validation_error(exc).info
        except WorkFLowWeaveError as exc:
            status, error = "failed", exc.info
        except ModelError as exc:
            status, error = "failed", exc.report or error_info(exc)
        except Exception as exc:
            status, error = "failed", error_info(exc)
        self._log("ai_call_cancelled" if status == "cancelled" else "ai_call_failed",
                  task_id, context, status=status, error_code=error.code)
        return AnalysisResult(task_id=task_id, status=status, error=error,
                              elapsed_ms=(time.perf_counter() - started) * 1000)

    async def _execute(self, config, model, messages, task_id, context):
        """在同一请求预算和渠道借用期内解析凭据、构造模型并执行重试。"""
        async with asyncio.timeout(config.timeout), self._model_lease(
            config, model=model, streaming=False, max_output_tokens=None,
        ) as (chat, credential):

            async def invoke():
                """用独立配置和消息副本发起一次 ainvoke，检查取消后再转换结果。"""
                message = await chat.ainvoke([item.model_copy(deep=True) for item in messages])
                _check_cancelled()
                return _result(message, task_id)

            return await self._retry(invoke, config, credential=credential,
                                     task_id=task_id, context=context)

    async def _retry(self, operation, config, *, credential, task_id, context):
        """按服务层分类有限重试，所有等待受外层总预算约束。

        最多尝试 1 + config.retries 次；只有 retryable 且非 uncertain 的错误
        可继续。每次失败立即记录日志并保存脱敏诊断，取消不进入异常重试分支。
        """
        for attempt in range(config.retries + 1):
            _check_cancelled()
            try:
                return await operation()
            except Exception as exc:
                error = model_error(exc)
                error.report = error_info(exc, credential=credential)
                retry = error.retryable and not error.uncertain and attempt < config.retries
                self._log("ai_attempt_failed", task_id, context, error_code=error.code,
                          status_code=error.status_code, attempt=attempt + 1,
                          will_retry=retry, uncertain=error.uncertain)
                if not retry:
                    if error is exc:
                        raise
                    raise error from exc
                _check_cancelled()
                await asyncio.sleep(_RETRY_DELAY * 2 ** min(attempt, 5))
        raise AssertionError("Unreachable retry state")

    @staticmethod
    def _log(event, task_id, context, **fields):
        """记录任务和 Workflow/session 关联字段，不将输入或错误正文放入摘要日志。"""
        _LOGGER.warning(event, extra={
            "event": event, "task_id": task_id,
            "workflow_id": context.workflow_id if context else None,
            "session_id": context.session_id if context else None, **fields,
        })

    async def close(self) -> None:
        """关闭全部渠道并拒绝新操作；重复调用等待同一清理结果。"""
        await self.channels.close()
