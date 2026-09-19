"""对服务端 mock 和可选 qwen3.7-flash 执行相同的真实 HTTP 验收。"""

import asyncio
import json

import httpx
import pytest

from ai.live_helpers import assert_success, call
from logagent.ai import AIService, OpenAIChannelFactory


async def test_model_discovery(channel_service, channel_config):
    """要求上游模型列表包含当前用例明确指定的模型 ID。"""
    config, _ = channel_config
    assert next(iter(config.models)) in await channel_service.list_models(config)


@pytest.mark.parametrize("options", [
    pytest.param({"enable_thinking": False}, id="thinking_off"),
    *(pytest.param({"enable_thinking": True, "reasoning_effort": effort}, id=effort)
      for effort in ("low", "medium", "high", "xhigh", "max")),
])
async def test_thinking_controls(observed_channel, channel_config, options):
    """比对真实请求中的思考参数，并验证有效回复及调用方配置不变。"""
    service, requests, _ = observed_channel
    config, _ = channel_config
    before = config.model_dump()
    result = await call(service, config, options)
    assert_success(result, config)
    assert config.model_dump() == before
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload["model"] == next(iter(config.models))
    assert {key: payload[key] for key in options} == options


async def test_concurrent_calls(channel_service, channel_config):
    """并发请求同一模型，验证每个成功结果保留各自的任务 ID。"""
    config, _ = channel_config
    results = await asyncio.gather(*(
        call(channel_service, config, {"enable_thinking": False}, task_id=f"parallel_{index}")
        for index in range(2)
    ))
    for index, result in enumerate(results):
        assert_success(result, config)
        assert result.task_id == f"parallel_{index}"


async def test_cancellation_notifies_and_closes_request(channel_config):
    """在请求钩子触发后取消任务，验证取消结果和一次通知。

    此断言针对本地取消处理，不证明上游已经收到请求或停止推理计费。
    """
    config, credentials = channel_config
    entered = asyncio.Event()
    notices = []

    async def request_started(request):
        """仅在聊天请求进入发送钩子时通知测试协程，避免误用模型发现请求。"""
        if request.url.path.endswith("/chat/completions"):
            entered.set()

    async with httpx.AsyncClient(timeout=None, event_hooks={"request": [request_started]}) as client:
        service = AIService(channel_factories={"http": OpenAIChannelFactory(client)},
                            credential_resolver=credentials)
        task = asyncio.create_task(call(service, config, {}, on_cancel=notices.append))
        try:
            await asyncio.wait_for(entered.wait(), config.timeout)
            task.cancel()
            result = await task
            assert result.status == "cancelled", result.model_dump_json()
            assert len(notices) == 1 and notices[0].channel_id == config.id
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await service.close()


async def test_closed_channel_requires_explicit_restart(channel_service, channel_config):
    """验证关闭后调用失败，只有显式重启后才能再次取得模型结果。"""
    config, _ = channel_config
    await channel_service.close_channel(config)
    result = await call(channel_service, config, {})
    assert result.status == "failed" and result.error.code == "channel_closed"
    await channel_service.start_channel(config)
    assert_success(await call(channel_service, config, {"enable_thinking": False}), config)
