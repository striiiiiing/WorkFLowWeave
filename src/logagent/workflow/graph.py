"""内容状态父图；业务能力通过闭包注入，不进入 checkpoint。"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from logagent.workflow.fan import build_work_subgraph
from logagent.workflow.notification import build_notification_graph
from logagent.workflow.stages import WorkflowOperations
from logagent.workflow.stream import tagged_node

GRAPH_REVISION = "workflow-content-v2"
PREDECESSORS = {"collect": START, "analyze": "collect", "aggregate": "analyze", "notify": "aggregate"}


def merge_items(left, right):
    return {**left, **right}


class ControlState(TypedDict):
    session_id: str
    execution_epoch: str
    stopped: bool
    status: str
    degraded: bool
    error: dict | None
    phase: dict


class CollectState(ControlState):
    collection_items: Annotated[dict, merge_items]
    shared_input: str


class AnalyzeState(ControlState):
    shared_input: str
    analysis_items: Annotated[dict, merge_items]


class NotifyState(ControlState):
    outputs: dict
    intents: Annotated[dict, merge_items]
    deliveries: Annotated[dict, merge_items]


class GraphState(ControlState):
    snapshot: dict
    log_path: str | None
    graph_revision: str
    shared_input: str
    analysis_items: dict
    outputs: dict
    aggregate_meta: dict | None
    intents: dict
    deliveries: dict
    stage_origins: dict
    resume_request_id: str | None
    resume_stage: str | None
    resume_checkpoint: str | None


def invoke_subgraph(subgraph):
    async def invoke(state, config: RunnableConfig):
        # LangGraph 1.2.12 tests presence, not value, of checkpoint_id when
        # deciding replay. Its parent supplies None for ordinary continuation.
        # Omit only that empty coordinate; real historical IDs remain explicit.
        configurable = config.get("configurable", {})
        if configurable.get("checkpoint_id") is None:
            config = {**config, "configurable": {
                key: value for key, value in configurable.items() if key != "checkpoint_id"
            }}
        return await subgraph.ainvoke(state, config)
    return invoke


def build_workflow(*, snapshot, context, checkpointer, collector_manager,
                   ai_service, channel_manager, registry=None):
    registry = {} if registry is None else registry
    operations = WorkflowOperations(snapshot, ai_service)
    graph = StateGraph(GraphState)
    for stage, schema in (("collect", CollectState), ("analyze", AnalyzeState)):
        graph.add_node(stage, invoke_subgraph(build_work_subgraph(
            stage=stage, snapshot=snapshot, context=context, operations=operations,
            state_schema=schema, collector_manager=collector_manager, registry=registry,
        )))
    graph.add_node("aggregate", tagged_node(registry, ("aggregate",), operations.aggregate, "workflow:aggregate"))
    graph.add_node("notify", invoke_subgraph(build_notification_graph(
        snapshot=snapshot, state_schema=NotifyState, arrange=operations.notification,
        channel_manager=channel_manager, uncertain=operations._uncertain, registry=registry,
    )))
    graph.add_node("finish", tagged_node(registry, ("finish",), operations.finish, "workflow:lifecycle"))
    graph.add_edge(START, "collect")
    for before, after in (("collect", "analyze"), ("analyze", "aggregate"), ("aggregate", "notify")):
        graph.add_conditional_edges(before, lambda state, after=after: "finish" if state["stopped"] else after,
                                    {"finish": "finish", after: after})
    graph.add_edge("notify", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)
