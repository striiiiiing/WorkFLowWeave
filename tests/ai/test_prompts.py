"""Workflow AI messages keep their layers and literal input content."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from logagent.ai import AIService
from logagent.ai.prompts import build_messages
from logagent.models import AIConfig
from tests.workflow_ai_helpers import TestChannelFactory, TestChatModel


@pytest.mark.parametrize("template,expected", [
    ("before {input} after", "before literal {input} after"),
    ("instruction", "literal {input}\n\ninstruction"),
    ("", "literal {input}"),
])
def test_three_independent_messages(template, expected):
    messages = build_messages(
        "system {input}", template, "literal {input}", user_prompt="difference {input}",
    )
    assert [type(message) for message in messages] == [SystemMessage, HumanMessage, HumanMessage]
    assert [message.content for message in messages] == [
        "system {input}", expected, "difference {input}",
    ]


def test_empty_difference_does_not_send_empty_message():
    messages = build_messages("", "{input}", "body")
    assert len(messages) == 2
    assert messages[1].content == "body"


async def test_ai_service_sends_three_messages_to_model(monkeypatch):
    seen = []

    async def record(self, messages, stop=None, run_manager=None, **kwargs):
        seen.append([(type(message), message.content) for message in messages])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    monkeypatch.setattr(TestChatModel, "_agenerate", record)
    service = AIService(channel_factories={"test": TestChannelFactory()})
    config = AIConfig(
        id="ai", provider="test", system_prompt="old AI system", models={"model": {}},
    )
    try:
        result = await service.execute(
            config, "{input}", "literal {input}", model="model",
            system_prompt="workflow system", user_prompt="difference {input}",
        )
        assert result.status == "success"
        assert seen == [[
            (SystemMessage, "workflow system"),
            (HumanMessage, "literal {input}"),
            (HumanMessage, "difference {input}"),
        ]]
        assert config.system_prompt == "old AI system"
    finally:
        await service.close()
