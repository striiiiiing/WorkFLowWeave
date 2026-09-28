"""原生 Send 展开投递分支；LangGraph 提交 intent 后才执行 receipt。"""

from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send

from logagent.workflow.execution.context import WorkflowContext
from logagent.workflow.graph.state import ControlState, merge_items

from .nodes.arrange import arrange
from .nodes.intent import intent
from .nodes.receipt import receipt


class BranchInput(TypedDict):
    session_id: str
    execution_epoch: str
    output_id: str
    channel_id: str
    text: str


class BranchOutput(TypedDict):
    intents: dict
    deliveries: dict


class BranchState(BranchInput, BranchOutput):
    pass


class State(ControlState):
    outputs: dict
    intents: Annotated[dict, merge_items]
    deliveries: Annotated[dict, merge_items]


class Output(ControlState, BranchOutput):
    pass


def dispatch(state, runtime: Runtime[WorkflowContext]):
    return [
        Send(
            "delivery",
            {
                "session_id": state["session_id"],
                "execution_epoch": state["execution_epoch"],
                "output_id": output_id,
                "channel_id": channel_id,
                "text": text,
            },
        )
        for output_id, text in state["outputs"].items()
        for channel_id in runtime.context.snapshot.workflow.channels
    ] or "arrange"


def build_notify():
    branch = StateGraph(
        BranchState,
        input_schema=BranchInput,
        output_schema=BranchOutput,
        context_schema=WorkflowContext,
    )
    branch.add_node("intent", intent)
    branch.add_node("receipt", receipt)
    branch.add_edge(START, "intent")
    branch.add_edge("intent", "receipt")
    branch.add_edge("receipt", END)
    compiled = branch.compile(checkpointer=None)

    builder = StateGraph(State, output_schema=Output, context_schema=WorkflowContext)
    builder.add_node("delivery", compiled.with_config(tags=["workflow:delivery"]))
    builder.add_node("arrange", arrange)
    builder.add_conditional_edges(START, dispatch, ["delivery", "arrange"])
    builder.add_edge("delivery", "arrange")
    builder.add_edge("arrange", END)
    return builder.compile(checkpointer=None)
