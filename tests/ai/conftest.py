"""AI HTTP 渠道验收夹具。

默认参数连接 localhost:19026/v1 的真实 mock 服务，WORKFLOWWEAVE_AI_LIVE=1
额外启用 Qwen；从环境文件解析配置与凭据。注入 HTTP 请求观察钩子，
不替换传输或制造响应；夹具负责关闭 AIService 和外部 HTTP 客户端。
"""

import os
from pathlib import Path

import httpx
import pytest

from tests.ai.live_helpers import Credentials, read_settings
from workflowweave.ai import AIService, OpenAIChannelFactory
from workflowweave.models import AIConfig

MOCK_BASE_URL = "http://localhost:19026/v1"


@pytest.fixture(params=[
    "mock",
    pytest.param("qwen3.7-flash", marks=pytest.mark.skipif(
        os.environ.get("WORKFLOWWEAVE_AI_LIVE") != "1",
        reason="Set WORKFLOWWEAVE_AI_LIVE=1 to also test qwen3.7-flash",
    )),
])
def channel_config(request):
    """为参数化用例准备渠道配置和凭据解析器。

    mock 固定请求 localhost:19026/v1；Qwen 使用配置文件中的地址。密钥由
    .env 或 WORKFLOWWEAVE_AI_ENV 指定文件读取，不启动应用或数据库。
    """
    settings = read_settings(Path(os.environ.get("WORKFLOWWEAVE_AI_ENV", ".env")))
    model = request.param
    config = AIConfig(
        id="acceptance", provider="openai_compatible_api",
        base_url=MOCK_BASE_URL if model == "mock" else settings["AI_BASE_URL"],
        api_key={"kind": "env", "name": "AI_API_KEY"} if settings.get("AI_API_KEY") else None,
        system_prompt="Follow the user's instruction. Reply with exactly WORKFLOWWEAVE_OK.",
        models={model: {}}, timeout=60, retries=0,
    )
    return config, Credentials(settings)


@pytest.fixture
async def channel_service(channel_config):
    """启动独立 AIService 供单个用例使用，并在用例退出时关闭渠道。"""
    config, credentials = channel_config
    service = AIService(channel_factories={"openai_compatible_api": OpenAIChannelFactory()},
                        credential_resolver=credentials)
    try:
        await service.start_channel(config)
        yield service
    finally:
        await service.close()


@pytest.fixture
async def observed_channel(channel_config):
    """提供服务、真实请求记录和外部客户端，供请求契约断言使用。

    只通过事件钩子观察实际请求，不替换 HTTP 传输或制造响应；夹具负责
    在 AIService 清理后关闭由其注入的 HTTP 客户端。
    """
    requests = []

    async def record(request):
        """记录即将发送的真实请求，不改变请求内容或阻断网络发送。"""
        requests.append(request)

    _, credentials = channel_config
    async with httpx.AsyncClient(timeout=None, event_hooks={"request": [record]}) as client:
        service = AIService(channel_factories={"openai_compatible_api": OpenAIChannelFactory(client)},
                            credential_resolver=credentials)
        try:
            yield service, requests, client
        finally:
            await service.close()
