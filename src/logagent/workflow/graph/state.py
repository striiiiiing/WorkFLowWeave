"""父图控制状态与局部阶段状态。"""

from __future__ import annotations

from typing import Annotated, TypedDict


def merge_items(left, right):
    return {**left, **right}


def same_identity(left, right):
    # BinaryOperatorAggregate initializes str channels with str().
    if left == "":
        return right
    if left != right:
        raise ValueError("Parallel Workflow branches disagree on execution identity")
    return left


class ControlState(TypedDict):
    session_id: Annotated[str, same_identity]
    execution_epoch: Annotated[str, same_identity]
    stopped: bool
    status: str
    degraded: bool
    error: dict | None
    phase: dict


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
