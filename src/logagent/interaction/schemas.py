"""Transport models that never duplicate business resource schemas."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator

from logagent.models import (
    ID,
    CronSchedule,
    DiscoveryReport,
    SessionStatus,
    SessionVersion,
    StrictModel,
    UTCDateTime,
    WorkflowSnapshot,
)


class CronPreviewRequest(CronSchedule):
    type: Literal["cron"] = "cron"


class CronPreviewResponse(StrictModel):
    description: str
    timezone: str
    next_run_at: UTCDateTime


class SessionListQuery(StrictModel):
    workflow_id: ID | None = None
    workflow_name: str | None = Field(default=None, min_length=1)
    session_id: ID | None = None
    status: SessionStatus | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    after: UTCDateTime | None = None
    before: UTCDateTime | None = None

    @model_validator(mode="after")
    def ordered_time_range(self) -> Self:
        if self.after is not None and self.before is not None and self.after > self.before:
            raise ValueError("after must not be later than before")
        return self


class SessionQuery(StrictModel):
    version: SessionVersion | None = None


class PhaseQuery(StrictModel):
    version: SessionVersion


class ReloadQuery(StrictModel):
    scope: Literal["resources", "plugins"] = "resources"


class TriggerRequest(StrictModel):
    workflow_id: ID | None = None
    snapshot: WorkflowSnapshot | None = None

    @model_validator(mode="after")
    def exactly_one_workflow(self) -> Self:
        if (self.workflow_id is None) == (self.snapshot is None):
            raise ValueError("workflow_id and snapshot are mutually exclusive")
        return self


class TriggerResponse(StrictModel):
    session_id: ID


class CancelResponse(StrictModel):
    session_id: ID
    cancelled: bool


class ReloadResponse(StrictModel):
    scope: Literal["resources", "plugins"]
    report: DiscoveryReport | None = None


class ProtectCredentialRequest(StrictModel):
    plaintext: SecretStr = Field(min_length=1)


class ResumeRequest(StrictModel):
    stage: Literal["collect", "analyze", "aggregate", "notify"] | None = None
    checkpoint_id: str | None = Field(default=None, min_length=1)
    request_id: ID | None = None


class RecoveryQuery(StrictModel):
    stage: Literal["collect", "analyze", "aggregate", "notify"] | None = None
    checkpoint_id: str | None = Field(default=None, min_length=1)
