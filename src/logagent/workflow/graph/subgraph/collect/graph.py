"""collect：原生 Send 展开单项子图，arrange 按原配置汇合。"""

from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from logagent.workflow.execution.context import WorkflowContext
from logagent.workflow.graph.state import ControlState, merge_items

from .nodes.arrange import arrange
from .nodes.collect import collect


class ItemInput(TypedDict):
    session_id: str
    execution_epoch: str
    source_id: str


class ItemOutput(TypedDict):
    collection_items: dict


class ItemState(ItemInput, ItemOutput):
    pass


class State(ControlState):
    shared_input: str
    input_views: list
    collection_items: Annotated[dict, merge_items]


class Output(ControlState):
    shared_input: str
    input_views: list


def dispatch(state, runtime: Runtime[WorkflowContext]):
    snapshot = runtime.context.snapshot
    return [
        Send(
            "item",
            {
                "session_id": state["session_id"],
                "execution_epoch": state["execution_epoch"],
                "source_id": ident,
            },
        )
        for ident in snapshot.workflow.sources
    ] or "arrange"


def build_collect():
    item = StateGraph(
        ItemState, input_schema=ItemInput, output_schema=ItemOutput, context_schema=WorkflowContext
    )
    item.add_node("work", collect)
    item.add_edge(START, "work")
    item.add_edge("work", END)
    compiled = item.compile(checkpointer=None)

    builder = StateGraph(State, output_schema=Output, context_schema=WorkflowContext)
    builder.add_node("item", compiled.with_config(tags=["workflow:collect:item"]))
    builder.add_node("arrange", arrange)
    builder.add_conditional_edges(START, dispatch, ["item", "arrange"])
    builder.add_edge("item", "arrange")
    builder.add_edge("arrange", END)
    return builder.compile(checkpointer=None)
