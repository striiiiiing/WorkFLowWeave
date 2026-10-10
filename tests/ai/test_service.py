"""AI 服务配置边界和真实请求契约测试。

纯配置用例参数化检查托管字段冲突、模型名与 JSON 参数；真实调用用例通过
HTTP 观察钩子核对角色、提示词替换、凭据、usage 和客户端所有权。
真实调用依赖 conftest 的本地 mock 服务，Qwen 参数由显式环境开关启用。
"""

import json

import pytest
from pydantic import ValidationError

from tests.ai.live_helpers import assert_success
from workflowweave.ai import AIService, OpenAIChannelFactory
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import AIConfig


def config():
    """提供纯配置校验使用的固定 mock 模型配置，不发起网络请求。"""
    return AIConfig(id="ai", provider="openai_compatible_api", models={"mock": {}},
                    base_url="http://localhost:19026/v1")


@pytest.mark.parametrize("field", [
    "model", "messages", "temperature", "top_k", "api_key", "base_url", "timeout",
    "max_retries", "stream", "extra_body",
])
def test_managed_options_cannot_override_request_settings(field):
    """验证模型扩展参数不能覆盖服务管理的字段，并明确返回冲突字段名。"""
    service = AIService(channel_factories={"openai_compatible_api": OpenAIChannelFactory()})
    cfg = config()
    cfg.models["mock"] = {field: "invalid"}
    with pytest.raises(WorkFLowWeaveError) as error:
        service.validate(cfg)
    assert error.value.code == "invalid_config"
    assert error.value.details["fields"] == [field]


@pytest.mark.parametrize("models", [{"": {}}, {"   ": {}}, {"mock": {"bad": float("nan")}}])
def test_models_require_explicit_nonempty_json_configuration(models):
    """验证模型集合、模型名和 JSON 参数必须符合显式配置契约。"""
    with pytest.raises(ValidationError):
        AIConfig(id="ai", provider="openai_compatible_api", models=models)


@pytest.mark.parametrize("prompt,input_text,expected", [
    ("read {input}", "{input} {other}", "read {input} {other}"),
    ("read", "body", "body\n\nread"),
])
async def test_request_roles_prompt_credentials_and_usage(
    observed_channel, channel_config, prompt, input_text, expected,
):
    """验证真实调用中的字面提示词、角色、认证、usage 和外部客户端所有权。"""
    service, requests, client = observed_channel
    cfg, credentials = channel_config
    cfg = cfg.model_copy(deep=True)
    cfg.system_prompt += " Treat braces such as {input} as literal text."
    model = next(iter(cfg.models))
    cfg.models[model] = {"enable_thinking": False}
    result = await service.execute(cfg, prompt, input_text, model=model)
    assert_success(result, cfg)
    assert len(requests) == 1
    request = requests[0]
    payload = json.loads(request.content)
    assert request.url.path.endswith("/v1/chat/completions")
    assert payload == {
        "model": model, "stream": False, "enable_thinking": False,
        "messages": [{"role": "system", "content": cfg.system_prompt},
                     {"role": "user", "content": expected}],
    }
    if cfg.api_key is not None:
        assert request.headers["authorization"] == "Bearer " + await credentials.resolve(cfg.api_key)
    assert result.usage["total_tokens"] > 0
    assert request.extensions["timeout"] == dict(connect=None, read=None, write=None, pool=None)
    await service.close()
    assert not client.is_closed


async def test_missing_credentials_fail_before_network(observed_channel, channel_config):
    """验证配置引用凭据但未提供解析器时立即失败，不产生网络请求。"""
    service, requests, _ = observed_channel
    cfg, _ = channel_config
    cfg = AIConfig.model_validate({**cfg.model_dump(), "api_key": {"kind": "env", "name": "KEY"}})
    service.credential_resolver = None
    result = await service.execute(cfg, "", "body", model=next(iter(cfg.models)))
    assert result.error.code == "credential_resolver_missing"
    assert requests == []


async def test_workflow_messages_keep_input_and_difference_separate(observed_channel, channel_config):
    service, requests, _ = observed_channel
    cfg, _ = channel_config
    model = next(iter(cfg.models))
    result = await service.execute(
        cfg, "input: {input}", "literal {input}", model=model,
        system_prompt="system {input}", user_prompt="difference {input}",
    )
    assert_success(result, cfg)
    payload = json.loads(requests[0].content)
    assert payload["messages"] == [
        {"role": "system", "content": "system {input}"},
        {"role": "user", "content": "input: literal {input}"},
        {"role": "user", "content": "difference {input}"},
    ]
    assert cfg.system_prompt != "system {input}"
    await service.close()
