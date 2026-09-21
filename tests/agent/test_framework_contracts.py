import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END

from tests.agent.helpers import ScriptedModel


async def test_summary_receives_entire_prefix_when_input_trimming_is_disabled():
    model = ScriptedModel(responses=[AIMessage(content="Preserved facts")])
    middleware = SummarizationMiddleware(
        model, trigger=("tokens", 2000), keep=("tokens", 100),
        trim_tokens_to_summarize=None,
    )
    messages = [
        HumanMessage(content="FIRST_FACT " + "history " * 10000 + " LAST_FACT"),
        AIMessage(content="Previous answer"), HumanMessage(content="Current question"),
    ]
    result = await middleware.abefore_model({"messages": messages}, None)
    prompt = model.seen[0][0].content
    assert len(prompt) > 70000
    assert "FIRST_FACT" in prompt and "LAST_FACT" in prompt
    assert result["messages"][-1].content == "Current question"


async def test_tool_runtime_failure_propagates_from_standard_agent():
    @tool
    async def fail():
        """Exercise a storage failure."""
        raise OSError("disk unavailable")

    model = ScriptedModel(responses=[AIMessage(content="", tool_calls=[
        {"id": "call", "name": "fail", "args": {}},
    ])])
    graph = create_agent(model, [fail])
    with pytest.raises(OSError, match="disk unavailable"):
        await graph.ainvoke({"messages": [HumanMessage(content="go")]})


async def test_pending_tool_can_be_repaired_without_replaying_side_effect(tmp_path):
    calls = []

    @tool
    async def effect():
        """Record a side effect."""
        calls.append("sent")
        return "sent"

    model = ScriptedModel(responses=[
        AIMessage(content="", tool_calls=[{"id": "old", "name": "effect", "args": {}}]),
        AIMessage(content="New answer"),
    ])
    config = {"configurable": {"thread_id": "session"}}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "agent.sqlite")) as saver:
        graph = create_agent(model, [effect], checkpointer=saver, interrupt_before=["tools"])
        await graph.ainvoke({"messages": [HumanMessage(content="Old question")]}, config)
        assert (await graph.aget_state(config)).next == ("tools",)
        graph = create_agent(model, [effect], checkpointer=saver)
        await graph.aupdate_state(config, {"messages": [
            ToolMessage(content="outcome_unknown", tool_call_id="old"),
        ]}, as_node="tools")
        await graph.aupdate_state(config, None, as_node=END)
        assert (await graph.aget_state(config)).next == ()
        result = await graph.ainvoke({"messages": [HumanMessage(content="New question")]}, config)
        assert result["messages"][-1].content == "New answer"
        assert calls == []
