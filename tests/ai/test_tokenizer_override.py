import json

import httpx
import pytest
import tiktoken

from workflowweave.ai import AIService, OpenAIChannelFactory
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import AIConfig


def config(tokenizer="gpt-4o"):
    return AIConfig(id="ai", provider="openai_compatible_api", base_url="http://model.test/v1",
                    models={"gpt-6-luna": {"tiktoken_model_name": tokenizer}}, retries=0)


def test_explicit_tokenizer_counts_real_tokens():
    text = "中文 news JSON: {\"value\":123}"
    assert AIService.input_counter(config(), "gpt-6-luna")(text) == len(
        tiktoken.get_encoding("o200k_base").encode(text)
    )


def test_unknown_tokenizer_fails_without_estimation():
    with pytest.raises(WorkFLowWeaveError, match="tokenizer"):
        AIService.input_counter(config("unknown-tokenizer"), "gpt-6-luna")


async def test_tokenizer_option_is_local_not_provider_payload():
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"index": 0, "message": {
            "role": "assistant", "content": "ok"}, "finish_reason": "stop"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = AIService(channel_factories={"openai_compatible_api": OpenAIChannelFactory(client)})
        try:
            async with service.lease(config(), model="gpt-6-luna") as model:
                assert model.tiktoken_model_name == "gpt-4o"
                assert model.get_num_tokens("test") == 1
                await model.ainvoke("go")
            assert "tiktoken_model_name" not in payloads[0]
        finally:
            await service.close()
