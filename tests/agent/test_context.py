import json
from copy import deepcopy

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from logagent.agent.config import AgentConfig
from logagent.agent.context.budget import estimate_request
from logagent.agent.context.compaction import ContextMiddleware, summarize_once
from logagent.agent.tools.declaration import ToolDeclaration
from logagent.ai import AIService, OpenAIChannelFactory
from logagent.errors import LogAgentError
from logagent.interaction.fastapi.agent import create_agent_service
from logagent.models import AIConfig
from tests.agent.helpers import ScriptedModel


class TokenizedModel(ScriptedModel):
    """Deterministic tokenizer so boundary tests do not depend on a provider."""

    def get_num_tokens_from_messages(self, messages, tools=None):
        return sum(len(message.content) + len(json.dumps(getattr(message, "tool_calls", [])))
                   for message in messages)


def small_config(**overrides):
    return AgentConfig(**{
        "context_window": 2000, "output_tokens": 100, "trigger_tokens": 1500,
        "keep_tokens": 100, "summary_max_tokens": 100, **overrides,
    })


def context(model, config=None, **kwargs):
    return ContextMiddleware(model=model, config=config or small_config(),
                             system_prompt=kwargs.pop("system_prompt", "fixed rules"),
                             tools=kwargs.pop("tools", []), **kwargs)


def test_config_exposes_fixed_token_defaults_without_obsolete_ratios():
    config = AgentConfig()
    assert (config.context_window, config.trigger_tokens, config.keep_tokens) == (
        200_000, 180_000, 40_000,
    )
    for name in ("trigger_ratio", "keep_ratio", "summary_ratio", "safety_ratio"):
        with pytest.raises(ValidationError):
            AgentConfig(**{name: 0.2})
    with pytest.raises(ValidationError):
        AgentConfig(keep_tokens=180_000)
    with pytest.raises(ValidationError):
        AgentConfig(summary_context_window=100, summary_max_tokens=100)


def test_complete_estimate_uses_tokenizer_and_known_model_capacity():
    model = TokenizedModel(responses=[], profile={"max_input_tokens": 1500})
    usage = estimate_request([HumanMessage(content="body")], "system", [{"name": "read"}],
                             small_config(), model=model)
    assert usage["messages"] > 0 and usage["system"] > 0 and usage["tools"] > 0
    assert usage["total"] == sum(usage[key] for key in ("messages", "system", "tools", "output"))
    assert usage["remaining"] == 1500 - usage["total"]
    assert usage["window"] == 1500
    assert usage["estimated"] is True
    assert usage["token_counter"] == "model_tokenizer"


def test_missing_tokenizer_is_labeled_but_unexpected_counting_errors_surface():
    class Unsupported(TokenizedModel):
        def get_num_tokens_from_messages(self, messages, tools=None):
            raise NotImplementedError("unrecognized model")

    class Broken(TokenizedModel):
        def get_num_tokens_from_messages(self, messages, tools=None):
            raise RuntimeError("tokenizer bug")

    usage = estimate_request([HumanMessage(content="body")], "", [], small_config(),
                             model=Unsupported(responses=[]))
    assert usage["token_counter"] == "framework_approximate"
    with pytest.raises(RuntimeError, match="tokenizer bug"):
        estimate_request([HumanMessage(content="body")], "", [], small_config(),
                         model=Broken(responses=[]))


async def test_missing_capacity_fails_before_model_but_known_profile_is_usable(tmp_path):
    for index, profile in enumerate((None, {"max_input_tokens": 100_000})):
        model = ScriptedModel(responses=[AIMessage(content="ok")], profile=profile)
        service = create_agent_service(tmp_path / str(index), tmp_path / f"runtime-{index}",
                               config=AgentConfig(context_window=None),
                               model_provider=lambda _, captured=model: captured)
        try:
            sid = (await service.create_session(model="test"))["session_id"]
            turn = await service.submit(sid, "hi", request_id="first")
            if profile is None:
                with pytest.raises(LogAgentError) as error:
                    await service.wait(turn["turn_id"])
                assert error.value.code == "context_budget_unavailable"
                assert not model.seen
            else:
                await service.wait(turn["turn_id"])
                assert len(model.seen) == 1
        finally:
            await service.close()


async def test_system_and_tools_trigger_one_summary_before_message_only_threshold():
    model = TokenizedModel(responses=[AIMessage(content="short summary")])
    messages = [HumanMessage(content="old fact " * 100, id="old"),
                HumanMessage(content="latest", id="latest")]
    middleware = context(model, system_prompt="prefix " * 75,
                         tools=[{"description": "tool " * 40}])
    assert middleware.counter(messages) < middleware.budget.trigger
    original = deepcopy(messages)
    result = await middleware.prepare(messages)
    assert result is not None
    assert len(model.seen) == 1
    assert messages == original
    compacted = add_messages([], result["messages"])
    assert compacted[-1].id == "latest"
    assert middleware.estimate(compacted)["total"] <= 2000


async def test_reported_usage_does_not_trigger_compaction_of_a_small_request():
    model = ScriptedModel(responses=[])
    messages = [HumanMessage(content="hi"), AIMessage(content="short", usage_metadata={
        "input_tokens": 199_000, "output_tokens": 1000, "total_tokens": 200_000,
    }, response_metadata={"model_provider": "openai"})]
    assert await context(model).prepare(messages) is None
    assert not model.seen


async def test_complete_long_summary_input_preserves_early_and_late_facts_and_tool_pairs():
    model = ScriptedModel(responses=[AIMessage(content="summary")])
    config = small_config(context_window=60_000, trigger_tokens=10_000, keep_tokens=100)
    messages = [HumanMessage(content="EARLY_FACT " + "history " * 14_000 + " LAST_OLD_FACT"),
                AIMessage(content="", tool_calls=[{"id": "call", "name": "read", "args": {}}]),
                ToolMessage(content="result", tool_call_id="call"),
                HumanMessage(content="latest")]
    compacted = await summarize_once(model, messages, config)
    assert len(model.seen) == 1
    prompt = model.seen[0][0].content
    assert len(prompt) > 100_000
    assert "EARLY_FACT" in prompt and "LAST_OLD_FACT" in prompt
    assert [type(message) for message in compacted[-3:]] == [AIMessage, ToolMessage, HumanMessage]


@pytest.mark.parametrize("independent", [False, True])
async def test_serialized_summary_prompt_capacity_is_checked_before_model(independent):
    model = TokenizedModel(responses=[])
    config = small_config(summary_ai="summary" if independent else None,
                          summary_context_window=1100,
                          summary_prompt="INSTRUCTIONS " * 50 + " {messages}")
    messages = [HumanMessage(content="old " * 300), HumanMessage(content="recent")]
    original = deepcopy(messages)
    with pytest.raises(LogAgentError) as error:
        await context(model, config, system_prompt="fixed " * 60).prepare(messages)
    assert error.value.code == "summary_context_budget_exceeded"
    assert error.value.info.details["total"] > 1100
    assert not model.seen
    assert messages == original


async def test_independent_summary_model_cannot_inherit_main_capacity():
    model = TokenizedModel(responses=[])
    messages = [HumanMessage(content="old " * 400), HumanMessage(content="recent")]
    with pytest.raises(LogAgentError) as error:
        await context(model, small_config(summary_ai="summary")).prepare(messages)
    assert error.value.code == "context_budget_unavailable"
    assert not model.seen


@pytest.mark.parametrize("response", ["still huge " * 200, "   "])
async def test_invalid_summary_never_retries_or_publishes_new_context(response):
    model = TokenizedModel(responses=[AIMessage(content=response)])
    messages = [HumanMessage(content="old " * 400), HumanMessage(content="recent")]
    original = deepcopy(messages)
    published = []

    async def publish(data):
        published.append(data)

    with pytest.raises(LogAgentError) as error:
        await context(model, on_compacted=publish).prepare(messages)
    assert error.value.code == ("context_compaction_failed" if not response.strip()
                                else "context_budget_exceeded")
    assert len(model.seen) == 1
    assert messages == original
    assert not published


async def test_summary_failure_preserves_original_message_ids_and_content():
    class BrokenSummary(TokenizedModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            self.seen.append(messages)
            raise RuntimeError("summary provider failed")

    model = BrokenSummary(responses=[])
    messages = [HumanMessage(content="old " * 400), HumanMessage(content="recent")]
    original = deepcopy(messages)
    with pytest.raises(RuntimeError, match="summary provider failed"):
        await context(model).prepare(messages)
    assert len(model.seen) == 1
    assert messages == original
    assert all(message.id is None for message in messages)


async def test_no_prefix_is_noop_for_manual_compact_and_fails_automatic_overflow():
    model = TokenizedModel(responses=[])
    middleware = context(model)
    assert await middleware.prepare([HumanMessage(content="short")], force=True) is None
    with pytest.raises(LogAgentError) as error:
        await middleware.prepare([HumanMessage(content="x" * 2000)])
    assert error.value.code == "context_budget_exceeded"
    assert not model.seen


@pytest.mark.parametrize("messages", [
    [ToolMessage(content="orphan", tool_call_id="missing")],
    [AIMessage(content="", tool_calls=[{"id": "missing", "name": "read", "args": {}}])],
])
async def test_incomplete_tool_groups_fail_explicitly(messages):
    with pytest.raises(LogAgentError) as error:
        await context(TokenizedModel(responses=[])).prepare(messages)
    assert error.value.code == "context_tool_pairing"


async def test_tool_result_growth_is_checked_before_the_next_model_request(tmp_path):
    async def invoke(arguments, context):
        return {"status": "success", "content": "result " * 3000}

    model = ScriptedModel(responses=[AIMessage(content="", tool_calls=[
        {"id": "large", "name": "large", "args": {}},
    ]), AIMessage(content="summary")])
    service = create_agent_service(
        tmp_path / "workspace", tmp_path / "runtime", config=small_config(keep_tokens=1400),
        model_provider=lambda _: model,
        declarations=[ToolDeclaration("large", "Large result", {"type": "object"}, "read", invoke)],
    )
    try:
        sid = (await service.create_session(model="test"))["session_id"]
        turn = await service.submit(sid, "run", request_id="first")
        with pytest.raises(LogAgentError) as error:
            await service.wait(turn["turn_id"])
        assert error.value.code == "context_budget_exceeded"
        assert len(model.seen) == 2
        assert model.seen[1][0].type == "human"
        events = await service.events(sid)
        assert sum(event["type"] == "tool.completed" for event in events) == 1
        assert events[-1]["error"]["code"] == "context_budget_exceeded"
        assert events[-1]["error"]["details"]["messages"] > 2000
    finally:
        await service.close()


async def test_old_checkpoint_history_is_checked_and_compaction_is_durable(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="old reply"),
                                     AIMessage(content="short summary"),
                                     AIMessage(content="new reply")])
    service = create_agent_service(tmp_path / "workspace", tmp_path / "runtime",
                           config=AgentConfig(output_tokens=100, summary_max_tokens=100),
                           model_provider=lambda _: model)
    try:
        sid = (await service.create_session(model="test"))["session_id"]
        first = await service.submit(sid, "EARLY_FACT " + "history " * 1000, request_id="first")
        await service.wait(first["turn_id"])
        service.update_config(small_config(context_window=5000, trigger_tokens=2000,
                                           keep_tokens=100, summary_context_window=10_000))
        second = await service.submit(sid, "latest", request_id="second")
        result = await service.wait(second["turn_id"])
        assert result["text"] == "new reply"
        assert len(model.seen) == 3
        assert "EARLY_FACT" in model.seen[1][0].content
        assert "EARLY_FACT" not in str(model.seen[2])
        assert model.seen[2][0].type == "system"
        events = await service.events(sid)
        compactions = [event for event in events if event["type"] == "context.compacted"]
        assert len(compactions) == 1
        compacted = compactions[0]
        saved = await service.workspace.read(compacted["artifact_path"], default_limit=200,
                                             output_bytes=16 * 1024 * 1024)
        assert "short summary" in saved["content"]
        assert compacted["removed_message_ids"]
        assert compacted["before"]["total"] > compacted["after"]["total"]
        assert (await service.get_session(sid))["context_budget"]["estimated"] is True
        assert sum(event["type"] == "message.user" for event in events) == 2
        assert not any(event["type"] == "message.delta" and
                       "short summary" in str(event.get("content")) for event in events)
    finally:
        await service.close()


async def test_real_provider_payload_matches_main_and_summary_reservations(tmp_path, monkeypatch):
    from langchain_openai import ChatOpenAI

    # This test exercises HTTP payloads, not tiktoken's first-use network download.
    monkeypatch.setattr(ChatOpenAI, "get_num_tokens_from_messages",
                        lambda self, messages, tools=None: count_tokens_approximately(messages))
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        answer = ["first answer", "internal summary", "final answer"][len(payloads) - 1]
        chunks = [
            {"id": str(len(payloads)), "choices": [{"index": 0, "delta": {
                "role": "assistant", "content": answer,
            }}]},
            {"id": str(len(payloads)), "choices": [
                {"index": 0, "delta": {}, "finish_reason": "stop"},
            ]},
        ]
        content = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                              content=content + "data: [DONE]\n\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        ai = AIService(channel_factories={"http": OpenAIChannelFactory(client)})
        service = create_agent_service(
            tmp_path / "workspace", tmp_path / "runtime", ai_service=ai,
            ai_config=AIConfig(id="ai", provider="http", base_url="http://model.test/v1",
                               models={"model": {"max_tokens": 9999}}, retries=0),
            config=AgentConfig(output_tokens=120, summary_max_tokens=60),
        )
        try:
            sid = (await service.create_session(model="model"))["session_id"]
            first = await service.submit(sid, "OLD_FACT " + "history " * 1000, request_id="one")
            await service.wait(first["turn_id"])
            service.update_config(small_config(
                context_window=5000, trigger_tokens=2000, keep_tokens=100,
                output_tokens=120, summary_max_tokens=60, summary_context_window=10_000,
            ))
            second = await service.submit(sid, "latest", request_id="two")
            assert (await service.wait(second["turn_id"]))["text"] == "final answer"
            assert [payload["max_completion_tokens"] for payload in payloads] == [120, 60, 120]
            assert all("max_tokens" not in payload for payload in payloads)
            assert payloads[0]["tools"] == payloads[2]["tools"]
            assert "tools" not in payloads[1]
            assert "OLD_FACT" in payloads[1]["messages"][0]["content"]
            events = await service.events(sid)
            assert [event["content"] for event in events if event["type"] == "message.delta"] == [
                "first answer", "final answer",
            ]
            assert [event["output"] for event in events if event["type"] == "context.budget"] == [
                120, 120,
            ]
        finally:
            await service.close()
            await ai.close()
