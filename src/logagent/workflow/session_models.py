"""业务存档的 SQLModel 表定义，沿用已有 SQLite 表名、字段与约束。"""

from sqlalchemy import Text, UniqueConstraint
from sqlmodel import Field, SQLModel


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
        primary_key=True, foreign_key="session_headers.session_id", sa_type=Text,
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
