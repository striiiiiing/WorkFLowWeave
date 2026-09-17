"""Explicit LangChain test models; never installed as production providers."""

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


class TestModelFactory:
    __test__ = False

    def __init__(self, responder=None):
        self.responder = responder

    def create(self, config, *, model, credential=None):
        return TestChatModel(
            responder=self.responder,
            arguments={"config": config, "model": model, "credential": credential},
            cache=False,
        )

    async def close(self):
        pass
