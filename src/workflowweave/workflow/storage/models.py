"""业务存档的 SQLModel 表定义，沿用已有 SQLite 表名、字段与约束。"""

from typing import Literal

from pydantic import Field as ModelField
from sqlalchemy import Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from workflowweave.model_base import StrictModel
from workflowweave.models import (
    ID,
    AnalysisResult,
    CollectionResult,
    DeliveryResult,
    ErrorInfo,
    InputView,
    Notification,
)


class SessionHeader(SQLModel, table=True):
    __tablename__ = "session_headers"

    session_id: str = Field(primary_key=True, sa_type=Text)
    workflow_id: str = Field(sa_type=Text)
    created_at: str = Field(sa_type=Text)
    policy: str = Field(sa_type=Text)


class SessionEntry(SQLModel, table=True):
    __tablename__ = "session_entries"
    __table_args__ = (UniqueConstraint("session_id", "write_key"),)

    session_id: str = Field(
        primary_key=True,
        foreign_key="session_headers.session_id",
        sa_type=Text,
    )
    version: int = Field(primary_key=True)
    write_key: str = Field(sa_type=Text)
    stage: str | None = Field(default=None, sa_type=Text)
    scope: str = Field(sa_type=Text)
    summary: str = Field(sa_type=Text)
    body: str | None = Field(default=None, sa_type=Text)
    availability: str = Field(sa_type=Text)
    category: str | None = Field(default=None, sa_type=Text)
    digest: str = Field(sa_type=Text)
    created_at: str = Field(sa_type=Text)


class CheckpointSource(SQLModel, table=True):
    __tablename__ = "workflow_checkpoint_sources"
    session_id: str = Field(primary_key=True)
    write_key: str = Field(primary_key=True)
    checkpoint_id: str = Field(primary_key=True)
    namespace: str = Field(primary_key=True)
    task_id: str = Field(primary_key=True)


class CollectionBody(SQLModel, table=True):
    __tablename__ = "workflow_collection_bodies"
    session_id: str = Field(primary_key=True)
    version: int = Field(primary_key=True)
    content: str = Field(sa_type=Text)


class AnalysisBody(SQLModel, table=True):
    __tablename__ = "workflow_analysis_bodies"
    session_id: str = Field(primary_key=True)
    version: int = Field(primary_key=True)
    content: str = Field(sa_type=Text)


class ReportBody(SQLModel, table=True):
    __tablename__ = "workflow_report_bodies"
    session_id: str = Field(primary_key=True)
    version: int = Field(primary_key=True)
    content: str = Field(sa_type=Text)


class PromptVersion(SQLModel, table=True):
    __tablename__ = "workflow_prompt_versions"
    digest: str = Field(primary_key=True)
    format_version: int = 1
    content: str = Field(sa_type=Text)


class ResultProvenance(SQLModel, table=True):
    __tablename__ = "workflow_result_provenance"
    session_id: str = Field(primary_key=True)
    version: int = Field(primary_key=True)
    details: str = Field(sa_type=Text)


class EpochRetention(SQLModel, table=True):
    __tablename__ = "workflow_epoch_retention"
    session_id: str = Field(primary_key=True)
    execution_epoch: str = Field(primary_key=True)
    policy: str = Field(sa_type=Text)
    anchor: str | None = Field(default=None, sa_type=Text)


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
    collection: list[CollectionResult] = ModelField(default_factory=list)
    shared_input: str = ""
    input_views: list[InputView] = ModelField(default_factory=list)
    analyses: list[AnalysisResult] = ModelField(default_factory=list)
    aggregate: AnalysisResult | None = None
    outputs: dict[str, str] = ModelField(default_factory=dict)
    notifications: list[Notification] = ModelField(default_factory=list)
    deliveries: list[DeliveryResult] = ModelField(default_factory=list)
    stopped: bool = False
    cancelled: bool = False
    errors: list[ErrorInfo] = ModelField(default_factory=list)

    @property
    def collection_results(self):
        """返回采集结果列表，作为 collection 字段的访问别名。"""
        return self.collection

    @property
    def analysis_results(self):
        """返回分析结果列表，作为 analyses 字段的访问别名。"""
        return self.analyses


BODY_TABLES = {"collection": CollectionBody, "analysis": AnalysisBody, "final": ReportBody}
TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled", "interrupted"}
