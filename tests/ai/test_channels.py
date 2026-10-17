"""AI HTTP 渠道发现与关闭契约测试。

参数化非法 thinking 选项检查调用前拒绝；通过真实 HTTP 渠道发现模型，
断言凭据传递、原配置保持不变，幂等关闭后请求被拒绝。
使用内存 HTTP 传输验证生产 SDK 请求，不读取用户配置或连接外部服务。
"""

import asyncio

import pytest

from tests.ai.live_helpers import assert_success, call
from workflowweave.ai import AIService, OpenAIChannelFactory
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import AIConfig


@pytest.mark.parametrize("options", [
    {"enable_thinking": "false"}, {"enable_thinking": 0}, {"reasoning_effort": None},
    {"reasoning_effort": []}, {"reasoning_effort": "extreme"},
    {"enable_thinking": False, "reasoning_effort": "low"},
])
def test_invalid_thinking_options_are_rejected(options):
    """验证非法思考参数在配置阶段被拒绝，无需发送模型请求。"""
    cfg = AIConfig(id="ai", provider="openai_compatible_api", base_url="http://localhost:19026/v1",
                   models={"mock": options})
    service = AIService(channel_factories={"openai_compatible_api": OpenAIChannelFactory()})
    with pytest.raises(WorkFLowWeaveError) as error:
        service.validate(cfg)
    assert error.value.code == "invalid_config"


async def test_discovery_preserves_config_and_uses_real_channel_credentials(
    observed_channel, channel_config,
):
    """验证并发启动不发探活请求，真实模型发现携带凭据且不覆盖模型配置。"""
    service, requests, _ = observed_channel
    cfg, credentials = channel_config
    before = cfg.model_dump()
    await asyncio.gather(*(service.start_channel(cfg) for _ in range(10)))
    assert requests == []
    assert next(iter(cfg.models)) in await service.list_models(cfg)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.path.endswith("/v1/models")
    if cfg.api_key is not None:
        assert request.headers["authorization"] == "Bearer " + await credentials.resolve(cfg.api_key)
    assert cfg.model_dump() == before


async def test_close_is_idempotent_and_blocks_requests(observed_channel, channel_config):
    """验证重复关闭安全，并在本地拒绝关闭后的调用而不触发网络请求。"""
    service, requests, _ = observed_channel
    cfg, _ = channel_config
    await service.start_channel(cfg)
    await asyncio.gather(service.close(), service.close())
    await service.close()
    result = await service.execute(cfg, "", "body", model=next(iter(cfg.models)))
    assert result.error.code == "ai_closed"
    assert requests == []


@pytest.mark.parametrize("options", [
    {"enable_thinking": False},
    *({"enable_thinking": True, "reasoning_effort": effort}
      for effort in ("low", "medium", "high", "xhigh", "max")),
])
async def test_thinking_options_reach_http_body(observed_channel, channel_config, options):
    """支持的配置选项原样进入请求，不要求特定供应商支持所有推理级别。"""
    import json

    service, requests, _ = observed_channel
    config, _ = channel_config
    before = config.model_dump()
    assert_success(await call(service, config, options), config)
    assert config.model_dump() == before
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert {key: payload[key] for key in options} == options
