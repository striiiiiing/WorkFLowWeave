"""Shared, versioned contracts. Stage contents never live in SessionRecord."""

import math
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, StrictBool, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$", strict=True)]
EnvironmentName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", strict=True)]
PositiveSeconds = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
PositiveInt = Annotated[int, Field(ge=1, strict=True)]
ArtifactName = Literal["snapshot", "collection", "analysis", "final"]
ARTIFACT_NAMES = ("snapshot", "collection", "analysis", "final")
ResourceKind = Literal["sources", "setters", "ai", "channels", "workflows"]


def utc_now() -> datetime:
    return datetime.now(UTC)


def validate_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, list):
        for item in value:
            validate_json_value(item)
        return value
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            validate_json_value(item)
        return value
    raise ValueError("Value must contain only JSON objects, arrays and scalar values")


def unique(values, label: str):
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicates")
    return values


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def timezone_required(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Datetime must include a timezone")
            return value.astimezone(UTC)
        return value


class SystemConfig(Model):
    data_dir: Path = Path("data")
    plugin_dir: Path = Path("plugins")
    host: str = "127.0.0.1"
    port: Annotated[int, Field(ge=1, le=65535, strict=True)] = 8000
    max_concurrent_runs: PositiveInt = 4
    log_file: Path | None = None
    _base_dir: Path = PrivateAttr(default_factory=Path.cwd)

    @property
    def base_dir(self) -> Path:
        return self._base_dir


class SourceConfig(Model):
    id: Identifier
    collector: Identifier
    options: dict[str, Any] = Field(default_factory=dict)
    setters: dict[str, Any] = Field(default_factory=dict)
    template: Identifier | None = None
    timeout: PositiveSeconds = 30
    on_error: Literal["stop", "skip"] = "stop"
    on_missing: Literal["stop", "skip"] = "stop"
    on_empty: Literal["stop", "skip"] = "skip"
    on_filtered_empty: Literal["stop", "skip"] = "skip"

    _json = field_validator("options", "setters", mode="before")(validate_json_value)


class SetterTemplate(Model):
    id: Identifier
    collector: Identifier
    setters: dict[str, Any] = Field(default_factory=dict)

    _json = field_validator("setters", mode="before")(validate_json_value)


class AIConfig(Model):
    id: Identifier
    provider: Identifier = "mock"
    model: Annotated[str, Field(min_length=1)] = "mock"
    base_url: str | None = None
    api_key_env: EnvironmentName | None = None
    system_prompt: str = ""
    model_options: dict[str, Any] = Field(default_factory=dict)
    tools: list[Identifier] = Field(default_factory=list)
    timeout: PositiveSeconds = 60

    @field_validator("model_options", mode="before")
    @classmethod
    def check_options(cls, value):
        validate_json_value(value)
        reserved = {
            "model",
            "messages",
            "tools",
            "tool_choice",
            "stream",
            "base_url",
            "api_key",
            "api_key_env",
            "headers",
            "timeout",
        }

        def walk(item):
            if isinstance(item, dict):
                for key, nested in item.items():
                    if key.lower() in {"temperature", "top_k"}:
                        raise ValueError(f"Unsupported model parameter: {key}")
                    walk(nested)
            elif isinstance(item, list):
                for nested in item:
                    walk(nested)

        walk(value)
        if isinstance(value, dict) and reserved.intersection(value):
            raise ValueError("Model options cannot override request control fields")
        return value

    @field_validator("tools")
    @classmethod
    def check_tools(cls, value):
        return unique(value, "tools")

    @field_validator("base_url")
    @classmethod
    def check_url(cls, value):
        if value is not None:
            message = "base_url must be an HTTP(S) URL without credentials, query or fragment"
            try:
                parsed = urlparse(value)
                _ = parsed.port  # Reject malformed and out-of-range ports as part of URL validation.
            except ValueError as exc:
                raise ValueError(message) from exc
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(message)
        return value


class ChannelConfig(Model):
    id: Identifier
    channel: Identifier
    options: dict[str, Any] = Field(default_factory=dict)
    timeout: PositiveSeconds = 30
    retries: Annotated[int, Field(ge=0, strict=True)] = 0
    enabled: StrictBool = True

    _json = field_validator("options", mode="before")(validate_json_value)


class AnalysisTask(Model):
    id: Identifier
    ai: Identifier
    prompt: str = "{input}"


class FanInConfig(Model):
    order: list[str] = Field(default_factory=list)
    separator: str = "\n\n"
    ai: Identifier | None = None
    prompt: str = "{input}"
    mark_incomplete: StrictBool = True

    @field_validator("order")
    @classmethod
    def check_order(cls, value):
        return unique(value, "fan_in.order")


class BackupPolicy(Model):
    enabled: StrictBool = True
    stages: list[ArtifactName] = Field(default_factory=lambda: list(ARTIFACT_NAMES))
    on_failure: Literal["stop", "continue"] = "stop"
    retention_days: PositiveSeconds | None = None

    @field_validator("stages")
    @classmethod
    def check_stages(cls, value):
        return unique(value, "backup.stages")


class WorkflowDefinition(Model):
    id: Identifier
    name: str = ""
    sources: Annotated[list[Identifier], Field(min_length=1)]
    analyses: Annotated[list[AnalysisTask], Field(min_length=1)]
    fan_in: FanInConfig | None = None
    channels: list[Identifier] = Field(default_factory=list)
    input_separator: str = "\n\n"
    include_counts: StrictBool = False
    collection_concurrency: PositiveInt = 4
    analysis_concurrency: PositiveInt = 4
    on_all_empty: Literal["stop", "skip"] = "stop"
    analysis_failure: Literal["stop", "continue"] = "continue"
    send_partial: StrictBool = True
    backup: BackupPolicy = Field(default_factory=BackupPolicy)
    interval_seconds: PositiveSeconds | None = None
    enabled: StrictBool = True

    @model_validator(mode="after")
    def validate_order(self):
        unique(self.sources, "sources")
        unique(self.channels, "channels")
        ids = unique([task.id for task in self.analyses], "analyses")
        if self.fan_in and set(self.fan_in.order) - set(ids) - {"$input"}:
            raise ValueError("fan_in.order refers to an unknown analysis")
        return self


class ErrorInfo(Model):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    _json = field_validator("details", mode="before")(validate_json_value)


class CollectionStatus(str, Enum):
    SUCCESS = "success"
    EMPTY = "empty"
    FILTERED_EMPTY = "filtered_empty"
    MISSING = "missing"
    FAILED = "failed"
    TIMEOUT = "timeout"


class AnalysisStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class DeliveryStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class CollectionResult(Model):
    source_id: Identifier
    status: CollectionStatus
    items: list[dict[str, Any]] = Field(default_factory=list)
    text: str = ""
    count: Annotated[int, Field(ge=0, strict=True)] = 0
    selected_count: Annotated[int, Field(ge=0, strict=True)] = 0
    error: ErrorInfo | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    _json = field_validator("items", "metadata", mode="before")(validate_json_value)


class AnalysisResult(Model):
    task_id: Identifier
    status: AnalysisStatus
    text: str = ""
    error: ErrorInfo | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)] = 0

    _json = field_validator("usage", mode="before")(validate_json_value)


class Notification(Model):
    session_id: Identifier
    output_id: Identifier
    title: str = ""
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    _json = field_validator("metadata", mode="before")(validate_json_value)


class DeliveryResult(Model):
    channel_id: Identifier
    output_id: Identifier
    status: DeliveryStatus
    attempts: Annotated[int, Field(ge=0, strict=True)] = 0
    error: ErrorInfo | None = None


class ArtifactInfo(Model):
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    size: Annotated[int, Field(ge=0, strict=True)]
    written_at: datetime
    expires_at: datetime | None = None


class SessionRecord(Model):
    id: Identifier
    workflow_id: Identifier
    status: SessionStatus = SessionStatus.CREATED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    stage: Literal["collect", "analyze", "aggregate", "notify", "finish"] = "collect"
    source_statuses: dict[str, CollectionStatus] = Field(default_factory=dict)
    analysis_statuses: dict[str, AnalysisStatus] = Field(default_factory=dict)
    deliveries: list[DeliveryResult] = Field(default_factory=list)
    errors: list[ErrorInfo] = Field(default_factory=list)
    artifacts: dict[ArtifactName, ArtifactInfo] = Field(default_factory=dict)
    recoverable: StrictBool = False
    missing_artifacts: dict[ArtifactName, str] = Field(default_factory=dict)
    output_frozen: StrictBool = False


class WorkflowSnapshot(Model):
    workflow: WorkflowDefinition
    sources: dict[str, SourceConfig]
    ai: dict[str, AIConfig]
    channels: dict[str, ChannelConfig]
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_resources(self):
        required_ai = {task.ai for task in self.workflow.analyses}
        if self.workflow.fan_in and self.workflow.fan_in.ai:
            required_ai.add(self.workflow.fan_in.ai)
        for name, resources, required in (
            ("sources", self.sources, set(self.workflow.sources)),
            ("ai", self.ai, required_ai),
            ("channels", self.channels, set(self.workflow.channels)),
        ):
            if set(resources) != required:
                raise ValueError(f"Snapshot {name} must contain exactly the referenced resources")
            if any(key != resource.id for key, resource in resources.items()):
                raise ValueError(f"Snapshot {name} keys must match resource IDs")
        return self


RESOURCE_MODELS = {
    "sources": SourceConfig,
    "setters": SetterTemplate,
    "ai": AIConfig,
    "channels": ChannelConfig,
    "workflows": WorkflowDefinition,
}
