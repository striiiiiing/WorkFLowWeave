"""直接装配五阶段父图；执行持久化完全交给注入的 LangGraph saver。"""

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph

from workflowweave.workflow.execution.context import WorkflowContext

from .state import GraphState
from .subgraph.aggregate.graph import build_aggregate
from .subgraph.analyze.graph import build_analyze
from .subgraph.collect.graph import build_collect
from .subgraph.nodes.cleanup import cleanup
from .subgraph.nodes.finish import finish
from .subgraph.notify.graph import build_notify

GRAPH_REVISION = "workflow-runtime-v4"
PREDECESSORS = {
    "collect": START,
    "analyze": "collect",
    "aggregate": "analyze",
    "notify": "aggregate",
}


def build_workflow(*, checkpointer):
    builder = StateGraph(GraphState, context_schema=WorkflowContext)
    builder.add_node("collect", build_collect())
    builder.add_node("analyze", build_analyze())
    builder.add_node("aggregate", build_aggregate())
    builder.add_node("notify", build_notify())
    builder.add_node("finish", RunnableLambda(finish).with_config(tags=["workflow:lifecycle"]))
    builder.add_edge(START, "collect")
    for before, after in (
        ("collect", "analyze"),
        ("analyze", "aggregate"),
        ("aggregate", "notify"),
    ):
        builder.add_conditional_edges(
            before,
            lambda state, after=after: "finish" if state["stopped"] else after,
            {"finish": "finish", after: after},
        )
    builder.add_edge("notify", "finish")
    builder.add_node("cleanup", cleanup, defer=True)
    builder.add_edge("finish", "cleanup")
    builder.add_edge("cleanup", END)
    return builder.compile(checkpointer=checkpointer)
