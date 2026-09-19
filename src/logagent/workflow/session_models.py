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
