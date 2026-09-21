from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class ScriptedModel(BaseChatModel):
    responses: list[AIMessage]
    seen: list[list[Any]] = Field(default_factory=list)
    bound_tools: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "scripted-agent-test"

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        response = self.responses[len(self.seen)]
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=response)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop, run_manager, **kwargs)
