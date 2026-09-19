"""使用配置校验和真实模型发现验证渠道边界与资源生命周期。"""

import asyncio

import pytest

from logagent.ai import AIService, OpenAIChannelFactory
from logagent.errors import LogAgentError
from logagent.models import AIConfig


@pytest.mark.parametrize("options", [
    {"enable_thinking": "false"}, {"enable_thinking": 0}, {"reasoning_effort": None},
    {"reasoning_effort": []}, {"reasoning_effort": "extreme"},
    {"enable_thinking": False, "reasoning_effort": "low"},
])
def test_invalid_thinking_options_are_rejected(options):
    """验证非法思考参数在配置阶段被拒绝，无需发送模型请求。"""
    cfg = AIConfig(id="ai", provider="http", base_url="http://localhost:19026/v1",
                   models={"mock": options})
    service = AIService(channel_factories={"http": OpenAIChannelFactory()})
    with pytest.raises(LogAgentError) as error:
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
