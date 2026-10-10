"""定义可注入的模型渠道协议，并实现 OpenAI 兼容的异步 HTTP 渠道。"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Protocol

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from openai import Omit

from workflowweave.ai.errors import ModelError
from workflowweave.models import AIConfig


class AIChannel(Protocol):
    """模型渠道的生命周期与调用边界。

    实现只负责连接、模型构造和发现；请求预算、重试及结果转换由 AIService 管理。
    """

    async def start(self) -> None:
        """准备渠道资源，使模型创建和模型发现可用。"""
        ...

    def create_model(
        self, config: AIConfig, *, model: str, credential: str | None,
        streaming: bool = False, max_output_tokens: int | None = None,
    ) -> BaseChatModel:
        """按已验证的配置和显式模型名创建独立聊天模型；credential 为已解析凭据。"""
        ...

    async def list_models(self, credential: str | None) -> list[str]:
        """使用指定凭据查询上游模型 ID；发现结果不写回用户配置。"""
        ...

    async def close(self) -> None:
        """释放渠道拥有的资源；外部注入资源的所有权由实现明确约定。"""
        ...


class ChannelFactory(Protocol):
    """将渠道配置转换为实例，供管理器注入不同的协议实现。"""

    def create(self, config: AIConfig) -> AIChannel:
        """从配置副本构造尚未启动的渠道，由管理器负责启动和关闭。"""
        ...


class OpenAIChannel:
    """通过共享异步客户端提供 Chat Completions 和模型发现。

    base_url 应包含兼容服务的 API 前缀，例如 /v1。每次调用创建独立模型，
    只共享连接，不保存对话历史或模型结果。
    """

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        """规范化 API 前缀并确定 HTTP 客户端所有权。

        Args:
            base_url: 已验证的渠道地址，末尾斜杠由渠道统一处理。
            client: 可选外部客户端；未传入时创建自有客户端，由 close 释放。

        客户端不设置阶段超时，由 AIService 的总预算控制请求时限。
        """
        self.base_url = base_url.rstrip("/") + "/"
        self.client = client if client is not None else httpx.AsyncClient(timeout=None)
        self._owned = client is None
        self._started = False
        self._closed = False

    async def start(self) -> None:
        """标记渠道可用，不向上游发送探活请求；已关闭的实例不能重新启动。"""
        if self._closed or self.client.is_closed:
            raise ModelError("channel_closed", "AI 渠道已关闭")
        self._started = True

    def _check_started(self) -> None:
        """拒绝使用未启动或已关闭的渠道，错误码为 channel_closed。"""
        if not self._started or self._closed:
            raise ModelError("channel_closed", "AI 渠道未启动或已关闭")

    def create_model(
        self, config, *, model, credential, streaming=False, max_output_tokens=None,
    ):
        """创建独立 ChatOpenAI，显式控制流式与实际输出预算。

        关闭 SDK 内部重试、缓存和阶段超时，避免与服务层重复管理。凭据通过
        异步 supplier 提供；credential 为 None 时显式省略认证头，防止读取环境密钥。
        """
        self._check_started()
        options = deepcopy(config.models[model])
        options.pop("streaming", None)
        tokenizer_model = options.pop("tiktoken_model_name", None)
        if max_output_tokens is not None:
            if type(max_output_tokens) is not int or max_output_tokens <= 0:
                raise ValueError("max_output_tokens must be a positive integer")
            # A single provider field owns the requested output budget.
            for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
                options.pop(key, None)
            options["max_completion_tokens"] = max_output_tokens

        async def api_key() -> str:
            """只返回本次已解析凭据，阻止 SDK 隐式使用环境中的 API key。"""
            return credential if credential is not None else ""

        return ChatOpenAI(
            model=model, base_url=self.base_url, api_key=api_key,
            http_async_client=self.client, openai_proxy=None, http_socket_options=(),
            model_kwargs={"extra_headers": {"Authorization": Omit()}} if credential is None else {},
            timeout=None, stream_chunk_timeout=None, max_retries=0, cache=False,
            streaming=streaming, stream_usage=streaming,
            tiktoken_model_name=tokenizer_model,
            disable_streaming=not streaming, use_responses_api=False,
            extra_body=options,
        )

    async def list_models(self, credential):
        """GET base_url/models，返回按上游顺序去重的模型 ID。

        HTTP 错误直接向上抛出；data 或 ID 结构不合法时抛出携带响应全文的
        ModelError。此方法不重试、不缓存，也不修改 AIConfig.models。
        """
        self._check_started()
        headers = {"Authorization": f"Bearer {credential}"} if credential is not None else {}
        response = await self.client.get(self.base_url + "models", headers=headers, timeout=None)
        response.raise_for_status()
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise ModelError(
                "invalid_response",
                "模型列表接口返回的不是有效 JSON；请检查服务地址是否包含正确的 API 路径（如 /v1）",
                status_code=response.status_code, response_body=response.text,
            ) from exc
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise ModelError("invalid_response", "模型列表响应缺少 data 数组",
                             response_body=response.text)
        names = []
        for item in body["data"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
                raise ModelError("invalid_response", "模型列表包含无效模型 ID",
                                 response_body=response.text)
            names.append(item["id"])
        return list(dict.fromkeys(names))

    async def close(self) -> None:
        """使实例永久不可用，并关闭自有 HTTP 客户端；外部客户端由注入者关闭。"""
        self._closed = True
        self._started = False
        if self._owned:
            await self.client.aclose()


class OpenAIChannelFactory:
    """为每个渠道构造独立连接池，或复用由调用方管理的外部客户端。"""

    def __init__(self, client: httpx.AsyncClient | None = None):
        """保存可选外部客户端；默认在创建各渠道时分别分配客户端。"""
        self.client = client

    def create(self, config: AIConfig) -> AIChannel:
        """使用已验证配置的 base_url 创建渠道，暂不启动或请求模型。"""
        return OpenAIChannel(config.base_url, self.client)
