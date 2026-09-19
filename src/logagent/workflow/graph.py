"""LangGraph 图定义与节点实现。

本模块只负责构造图及实现图节点；运行准入、生命周期、恢复校验和
后台任务句柄由 :mod:`workflow.service` 管理。每个阶段以显式节点注册，
通知的意图、发送和回执也分别是图节点。
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from logagent.errors import LogAgentError, exception_error
from logagent.workflow.nodes import archive_node
from logagent.workflow.stages import StageNodes

_STAGES = ("collect", "analyze", "aggregate", "notify", "finish")


def _merge(left, right):
    return {**left, **right}


class GraphState(TypedDict):
    session_id: str
    phases: Annotated[dict[str, str], _merge]
    stopped: bool
    status: str
    generation: int
    retry_stage: str | None


class ChildState(GraphState):
    items: Annotated[dict[str, str], _merge]


def _safe_node(operation):
    async def node(state):
        try:
            return await operation(state)
        except LogAgentError:
            raise
        except Exception as exc:
            error = exception_error(exc, code="workflow_failed", message="Workflow 节点执行或存档失败")
            raise LogAgentError(error.code, error.message, error.details) from None
    return node


class WorkflowGraph:

    def __init__(self, *, runtime, snapshot, context, checkpointer, collector_manager, ai_service, channel_manager):
        self.runtime = runtime
        self.snapshot = snapshot
        self.context = context
        self.checkpointer = checkpointer
        self.stages = StageNodes(runtime, snapshot, collector_manager, ai_service, channel_manager, context)

    async def result(self, state, *, required=()):
        return await self.stages._result(state, required=required)

    def compile(self):
        return self._graph()

    def snapshot_node(self):
        return self.stages.snapshot_node()

    def _graph(self):
        from logagent.workflow.fan import build_work_subgraph
        from logagent.workflow.notification import build_notification_graph
        graph = StateGraph(GraphState)
        graph.add_node("snapshot", _safe_node(self.snapshot_node()))
        for stage in ("collect", "analyze"):
            graph.add_node(stage, build_work_subgraph(
                stage=stage, runtime=self.runtime, snapshot=self.snapshot, context=self.context,
                stage_nodes=self.stages, state_schema=ChildState,
                collector_manager=self.stages.collector_manager, safe_node=_safe_node,
            ))
        graph.add_node("aggregate", self.stages._phase_node("aggregate", self.runtime, self.snapshot))
        graph.add_node("notify", build_notification_graph(
            runtime=self.runtime, snapshot=self.snapshot, state_schema=GraphState,
            result_reader=lambda state, *, required=(): self.stages._result(state, required=required),
            phase_node_factory=lambda stage: self.stages._phase_node(stage, self.runtime, self.snapshot),
            channel_manager=self.stages.channel_manager, safe_node=_safe_node,
            uncertain=self.stages._uncertain,
        ))
        graph.add_node("finish", self.stages._phase_node("finish", self.runtime, self.snapshot))
        for stage in _STAGES:
            async def start_body(state, stage=stage):
                return {"status": "running"}
            graph.add_node(f"start_{stage}", archive_node(
                self.runtime, scope="parent", stage=stage, key=f"started:{stage}",
                operation=start_body, category=None, summarize=lambda body: body,
                publish=lambda key, summary: {},
            ))
            graph.add_edge(f"start_{stage}", stage)
        graph.add_edge(START, "snapshot")
        graph.add_edge("snapshot", "start_collect")
        for before, after in (("collect", "analyze"), ("analyze", "aggregate"), ("aggregate", "notify")):
            graph.add_conditional_edges(before, lambda state, after=after: "finish" if state["stopped"] else after,
                                        {"finish": "start_finish", after: f"start_{after}"})
        graph.add_edge("notify", "start_finish")
        graph.add_edge("finish", END)
        return graph.compile(checkpointer=self.checkpointer)

