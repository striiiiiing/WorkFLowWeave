"""直接以业务节点和 per-invocation 子图装配 Workflow。"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from logagent.workflow.fan import build_work_subgraph
from logagent.workflow.nodes import safe_node
from logagent.workflow.notification import build_notification_graph
from logagent.workflow.stages import WorkflowOperations
from logagent.workflow.stream import tagged_node

GRAPH_REVISION = "workflow-stream-v1"
PREDECESSORS = {"collect": START, "analyze": "collect", "aggregate": "analyze", "notify": "aggregate"}


def _merge(left, right):
    return {**left, **right}


class GraphState(TypedDict):
    session_id: str
    snapshot_ref: str
    phases: Annotated[dict[str, str], _merge]
    stopped: bool
    status: str
    graph_revision: str
    execution_epoch: str
    deliveries: Annotated[dict[str, str], _merge]
    resume_request_id: str | None
    resume_stage: str | None
    resume_checkpoint: str | None


class ChildState(GraphState):
    items: Annotated[dict[str, str], _merge]


def build_workflow(*, runtime, snapshot, context, checkpointer, collector_manager,
                   ai_service, channel_manager, registry=None):
    registry = {} if registry is None else registry
    operations = WorkflowOperations(
        runtime, snapshot, collector_manager, ai_service, channel_manager, context,
    )
    graph = StateGraph(GraphState)
    for stage in ("collect", "analyze"):
        graph.add_node(stage, build_work_subgraph(
            stage=stage, runtime=runtime, snapshot=snapshot, context=context,
            stage_nodes=operations, state_schema=ChildState,
            collector_manager=collector_manager, safe_node=safe_node, registry=registry,
        ))
    graph.add_node("aggregate", tagged_node(
        registry, ("aggregate",), operations.aggregate_node(), "workflow:aggregate",
    ))
    graph.add_node("notify", build_notification_graph(
        runtime=runtime, snapshot=snapshot, state_schema=GraphState,
        result_reader=operations.result,
        arrange=operations.notification_result_node(),
        channel_manager=channel_manager, safe_node=safe_node, uncertain=operations._uncertain,
        registry=registry,
    ))
    graph.add_node("finish", tagged_node(
        registry, ("finish",), operations.finish_node(), "workflow:lifecycle",
    ))
    graph.add_edge(START, "collect")
    for before, after in (("collect", "analyze"), ("analyze", "aggregate"), ("aggregate", "notify")):
        graph.add_conditional_edges(
            before, lambda state, after=after: "finish" if state["stopped"] else after,
            {"finish": "finish", after: after},
        )
    graph.add_edge("notify", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)
