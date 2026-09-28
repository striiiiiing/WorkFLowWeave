"""Probe native LangGraph Runtime, Send, subgraph, tags, and defer APIs."""

import asyncio
import operator
from typing import Annotated, TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

ITEM_TAG = "workflow:probe:item"


def merge_results(left: dict[str, str], right: dict[str, str]) -> dict[str, str]:
    return {**left, **right}


class GraphContext(TypedDict):
    marker: str


class RootState(TypedDict):
    ids: list[str]
    results: Annotated[dict[str, str], merge_results]


class ItemInput(TypedDict):
    item_id: str


class ItemOutput(TypedDict):
    results: dict[str, str]


class ItemState(ItemInput, ItemOutput):
    private_value: str


class DeferredState(TypedDict):
    events: Annotated[list[str], operator.add]


@pytest.mark.asyncio
async def test_send_propagates_runtime_to_native_tagged_subgraph_and_limits_stream_channels():
    async def run_item(state: ItemState, runtime: Runtime[GraphContext]):
        marker = runtime.context["marker"]
        return {
            "results": {state["item_id"]: marker},
            "private_value": "must not escape the output schema",
        }

    item_builder = StateGraph(
        ItemState,
        context_schema=GraphContext,
        input_schema=ItemInput,
        output_schema=ItemOutput,
    )
    item_builder.add_node("work", run_item)
    item_builder.add_edge(START, "work")
    item_builder.add_edge("work", END)
    item = item_builder.compile()
    tagged_item = item.with_config(tags=[ITEM_TAG])

    async def dispatch(_state: RootState):
        return {}

    def send_items(state: RootState):
        return [Send("item", {"item_id": item_id}) for item_id in state["ids"]]

    root_builder = StateGraph(RootState, context_schema=GraphContext)
    root_builder.add_node("dispatch", dispatch)
    root_builder.add_node("item", tagged_item)
    root_builder.add_edge(START, "dispatch")
    root_builder.add_conditional_edges("dispatch", send_items)
    root_builder.add_edge("item", END)
    graph = root_builder.compile()

    assert "item" in dict(graph.get_subgraphs())

    initial = {"ids": ["first", "second"], "results": {}}
    context = {"marker": "runtime-context"}
    result = await graph.ainvoke(initial, context=context)
    assert result == {
        "ids": ["first", "second"],
        "results": {"first": "runtime-context", "second": "runtime-context"},
    }

    child_values = []
    async for part in graph.astream(
        initial,
        context=context,
        stream_mode="values",
        subgraphs=True,
    ):
        if isinstance(part, tuple) and len(part) == 2:
            namespace, value = part
            if namespace:
                child_values.append(value)
    assert child_values
    assert all("private_value" not in value for value in child_values)

    events = [
        event
        async for event in graph.astream_events(
            initial,
            context=context,
            version="v2",
            subgraphs=True,
        )
    ]
    tagged_events = [event for event in events if ITEM_TAG in event["tags"]]
    assert tagged_events
    assert any(event["event"] == "on_chain_start" for event in tagged_events)


@pytest.mark.asyncio
async def test_deferred_node_waits_for_all_normal_branches(tmp_path):
    events = []
    fast_done = asyncio.Event()
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()

    async def fast(_state):
        events.append("fast")
        fast_done.set()
        return {"events": ["fast"]}

    async def slow(_state):
        slow_started.set()
        await release_slow.wait()
        events.append("slow")
        return {"events": ["slow"]}

    async def deferred(_state):
        events.append("deferred")
        return {"events": ["deferred"]}

    builder = StateGraph(DeferredState)
    builder.add_node("fast", fast)
    builder.add_node("slow", slow)
    builder.add_node("deferred", deferred, defer=True)
    for node in ("fast", "slow", "deferred"):
        builder.add_edge(START, node)
        builder.add_edge(node, END)
    graph = builder.compile()

    invocation = asyncio.create_task(graph.ainvoke({"events": []}))
    try:
        async with asyncio.timeout(5):
            await asyncio.gather(fast_done.wait(), slow_started.wait())
        assert events == ["fast"]

        release_slow.set()
        result = await asyncio.wait_for(invocation, timeout=5)
        assert events[-1] == "deferred"
        assert events.index("fast") < events.index("deferred")
        assert events.index("slow") < events.index("deferred")
        assert result["events"] == ["fast", "slow", "deferred"]
    finally:
        release_slow.set()
        if not invocation.done():
            invocation.cancel()
        await asyncio.gather(invocation, return_exceptions=True)


@pytest.mark.asyncio
async def test_deferred_node_does_not_run_after_normal_node_failure():
    deferred_calls = []

    async def fail(_state):
        raise RuntimeError("primary branch failed")

    async def deferred(_state):
        deferred_calls.append("called")
        return {"events": ["deferred"]}

    builder = StateGraph(DeferredState)
    builder.add_node("fail", fail)
    builder.add_node("deferred", deferred, defer=True)
    builder.add_edge(START, "fail")
    builder.add_edge(START, "deferred")
    builder.add_edge("fail", END)
    builder.add_edge("deferred", END)
    graph = builder.compile()

    with pytest.raises(RuntimeError, match="primary branch failed"):
        await asyncio.wait_for(graph.ainvoke({"events": []}), timeout=5)
    assert not deferred_calls


@pytest.mark.asyncio
async def test_interrupt_before_deferred_node_leaves_it_pending():
    deferred_calls = []

    async def normal(_state):
        return {"events": ["normal"]}

    async def deferred(_state):
        deferred_calls.append("called")
        return {"events": ["deferred"]}

    builder = StateGraph(DeferredState)
    builder.add_node("normal", normal)
    builder.add_node("deferred", deferred, defer=True)
    builder.add_edge(START, "normal")
    builder.add_edge(START, "deferred")
    builder.add_edge("normal", END)
    builder.add_edge("deferred", END)
    graph = builder.compile(
        checkpointer=InMemorySaver(),
        interrupt_before=["deferred"],
    )
    config = {"configurable": {"thread_id": "deferred-interrupt"}}

    await graph.ainvoke({"events": []}, config=config)
    state = await graph.aget_state(config)
    assert state.next == ("deferred",)
    assert state.values["events"] == ["normal"]
    assert not deferred_calls
