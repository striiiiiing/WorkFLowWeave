from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from logagent.workflow.execution.context import WorkflowContext
from logagent.workflow.graph.state import ControlState

from .nodes.aggregate import aggregate


class Input(ControlState):
    shared_input: str
    analysis_items: dict


class State(Input):
    outputs: dict
    aggregate_meta: dict | None


def dispatch(state):
    return Send("aggregate", state)


def build_aggregate():
    builder = StateGraph(State, input_schema=Input, context_schema=WorkflowContext)
    builder.add_node("aggregate", aggregate)
    builder.add_conditional_edges(START, dispatch, ["aggregate"])
    builder.add_edge("aggregate", END)
    return builder.compile(checkpointer=None).with_config(tags=["workflow:aggregate"])
