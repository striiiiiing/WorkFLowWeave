"""普通 AI 测试使用固定 HTTP 传输；live 标记才连接显式配置的真实服务。"""

import os
from pathlib import Path

import httpx
import pytest

from tests.ai.live_helpers import Credentials, read_settings
from workflowweave.ai import AIService, OpenAIChannelFactory
from workflowweave.models import AIConfig


def _mock_response(request: httpx.Request) -> httpx.Response:
    """只在测试中替换 HTTP 传输，仍经过生产 SDK 的请求序列化与结果解析。"""
    if request.method == "GET" and request.url.path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": "test-model"}]})
    if request.method == "POST" and request.url.path == "/v1/chat/completions":
        return httpx.Response(200, json={
            "id": "test-completion",
            "object": "chat.completion",
            "model": "test-model",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "WORKFLOWWEAVE_OK"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        })
    raise AssertionError(f"Unexpected test request: {request.method} {request.url}")


@pytest.fixture
def channel_config(request):
    """普通测试不读取用户配置；live 验收严格读取指定地址、模型与凭据。"""
    if request.node.get_closest_marker("live"):
        settings = read_settings(Path(os.environ.get("WORKFLOWWEAVE_AI_ENV", ".env")))
    else:
        settings = {
            "AI_BASE_URL": "http://provider.test/v1",
            "AI_MODEL": "test-model",
            "AI_API_KEY": "test-only-credential",
        }
    config = AIConfig(
        id="acceptance", provider="openai_compatible_api",
        base_url=settings["AI_BASE_URL"],
        api_key={"kind": "env", "name": "AI_API_KEY"} if settings.get("AI_API_KEY") else None,
        system_prompt="Follow the user's instruction. Reply with exactly WORKFLOWWEAVE_OK.",
        models={settings["AI_MODEL"]: {}}, timeout=15, retries=0,
    )
    return config, Credentials(settings)


@pytest.fixture
async def observed_channel(request, channel_config):
    """记录生产 SDK 构造的请求，并由夹具管理注入的 HTTP 客户端。"""
    requests = []

    async def record(request):
        requests.append(request)

    _, credentials = channel_config
    transport = None if request.node.get_closest_marker("live") else httpx.MockTransport(_mock_response)
    async with httpx.AsyncClient(
        timeout=None, transport=transport, event_hooks={"request": [record]},
    ) as client:
        service = AIService(
            channel_factories={"openai_compatible_api": OpenAIChannelFactory(client)},
            credential_resolver=credentials,
        )
        try:
            yield service, requests, client
        finally:
            await service.close()


@pytest.fixture
async def channel_service(observed_channel, channel_config):
    """使用同一客户端所有权规则启动渠道，清理由 observed_channel 负责。"""
    service, _, _ = observed_channel
    config, _ = channel_config
    await service.start_channel(config)
    return service
