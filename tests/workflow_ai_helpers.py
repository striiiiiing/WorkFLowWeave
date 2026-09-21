"""跨模块集成测试复用的 LangChain 模型与渠道替身。

工厂把配置、模型、凭据和提示词传给可同步或异步的 responder，再将结果
封装为 ChatResult；同步模型入口直接失败，保证测试走 AIService 异步调用链。
仅替换模型传输层，不注册生产 provider，也不访问外部模型服务。
"""

import inspect
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class TestChatModel(BaseChatModel):
    __test__ = False
    responder: Any = None
    arguments: dict[str, Any]

    @property
    def _llm_type(self):
        return "test-chat"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise AssertionError("AIService must use the asynchronous Model API")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        arguments = {**self.arguments, "system": messages[0].content, "user": messages[1].content}
        value = {"text": arguments["user"]} if self.responder is None else self.responder(**arguments)
        if inspect.isawaitable(value):
            value = await value
        message = value if isinstance(value, AIMessage) else AIMessage(
            content=value["text"], response_metadata={"token_usage": value.get("usage", {})},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class TestChannelFactory:
    __test__ = False

    def __init__(self, responder=None):
        self.responder = responder

    def create(self, config):
        return TestChannel(self, config)

    def create_model(self, config, *, model, credential=None, streaming=False, max_output_tokens=None):
        return TestChatModel(
            responder=self.responder,
            arguments={"config": config, "model": model, "credential": credential},
            cache=False,
        )

    async def close(self):
        pass


class TestChannel:
    def __init__(self, factory, config):
        self.factory, self.config = factory, config

    async def start(self):
        pass

    def create_model(self, config, *, model, credential, streaming=False, max_output_tokens=None):
        return self.factory.create_model(
            config, model=model, credential=credential,
            streaming=streaming, max_output_tokens=max_output_tokens,
        )

    async def list_models(self, credential):
        return list(self.config.models)

    async def close(self):
        await self.factory.close()
