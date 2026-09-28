"""Workflow 只读业务结果模型，不参与执行调度。"""
from typing import Literal

from pydantic import Field

from logagent.models import (
    ID,
    AnalysisResult,
    CollectionResult,
    DeliveryResult,
    ErrorInfo,
    Notification,
    StrictModel,
)


class WorkflowResult(StrictModel):
    """一次运行的业务结果，按阶段存档逐步组装。

    collection、analyses 保持定义顺序；outputs 是通知使用的冻结输出。
    stopped 表示不再进入下游业务阶段，并不必然表示失败，例如全空跳过。
    """
    session_id: ID
    workflow_id: ID
    stage: Literal["collect", "analyze", "aggregate", "notify", "finish"] = "collect"
    status: Literal["running", "completed", "partial", "failed", "cancelled", "interrupted"] = (
        "running"
    )
    collection: list[CollectionResult] = Field(default_factory=list)
    shared_input: str = ""
    analyses: list[AnalysisResult] = Field(default_factory=list)
    aggregate: AnalysisResult | None = None
    outputs: dict[str, str] = Field(default_factory=dict)
    notifications: list[Notification] = Field(default_factory=list)
    deliveries: list[DeliveryResult] = Field(default_factory=list)
    stopped: bool = False
    cancelled: bool = False
    errors: list[ErrorInfo] = Field(default_factory=list)

    @property
    def collection_results(self):
        """返回采集结果列表，作为 collection 字段的访问别名。"""
        return self.collection

    @property
    def analysis_results(self):
        """返回分析结果列表，作为 analyses 字段的访问别名。"""
        return self.analyses


def collection_input(workflow, items):
    valid = [item["text"] for item in items if item["status"] == "success"]
    text = workflow.input_separator.join(valid)
    if workflow.include_counts and valid:
        text += "\n\n" + "\n".join(f"{item['source_id']}: {item['status']} ({item['count']})" for item in items)
    return text


