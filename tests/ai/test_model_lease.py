import asyncio
import json

import httpx
import pytest

from workflowweave.ai import AIService, OpenAIChannelFactory
from workflowweave.ai.errors import ModelError
from workflowweave.models import AIConfig


def config():
    return AIConfig(
        id="ai", provider="http", base_url="http://model.test/v1",
        models={"model": {"max_tokens": 77}}, retries=0,
    )


async def test_lease_streams_tools_and_applies_one_actual_output_budget():
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        chunks = [
            {"choices": [{"index": 0, "delta": {"role": "assistant", "content": "hello"}}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                              content=body + "data: [DONE]\n\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = AIService(channel_factories={"http": OpenAIChannelFactory(client)})
        cfg = config()
        before = cfg.model_dump()
        async with service.lease(cfg, model="model", streaming=True, max_output_tokens=120) as chat:
            bound = chat.bind_tools([{
                "name": "read", "description": "Read text",
                "parameters": {"type": "object", "properties": {}},
            }])
            text = "".join([chunk.content async for chunk in bound.astream("go")])
        assert text == "hello"
        assert payloads[0]["stream"] is True
        assert payloads[0]["max_completion_tokens"] == 120
        assert "max_tokens" not in payloads[0]
        assert payloads[0]["tools"][0]["function"]["name"] == "read"
        assert cfg.model_dump() == before
        await service.close()
        assert not client.is_closed


async def test_lease_does_not_mask_tool_or_storage_failures():
    service = AIService(channel_factories={"http": OpenAIChannelFactory()})
    try:
        with pytest.raises(OSError, match="storage failed"):
            async with service.lease(config(), model="model"):
                raise OSError("storage failed")
    finally:
        await service.close()


async def test_channel_close_cancels_entire_model_lease():
    service = AIService(channel_factories={"http": OpenAIChannelFactory()})
    entered = asyncio.Event()

    async def run():
        async with service.lease(config(), model="model"):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run())
    await entered.wait()
    await service.close()
    assert task.cancelled()


async def test_lease_redacts_known_credentials_in_upstream_error():
    class Credentials:
        async def resolve(self, credential):
            return "test-private-token"

    service = AIService(channel_factories={"http": OpenAIChannelFactory()},
                        credential_resolver=Credentials())
    cfg = AIConfig.model_validate({
        **config().model_dump(), "api_key": {"kind": "env", "name": "TEST_KEY"},
    })
    try:
        with pytest.raises(ModelError) as error:
            async with service.lease(cfg, model="model"):
                raise ModelError("provider_rejected", "test-private-token denied")
        assert "test-private-token" not in error.value.report.model_dump_json()
    finally:
        await service.close()
