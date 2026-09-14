"""Strict, JSON-compatible exchange models from the OpenSpec contracts.

Runtime dependencies live in CollectionContext, outside the serialized models.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

if TYPE_CHECKING:
    from logagent.protocols import CredentialResolver

def _json_value(value: Any) -> Any:
    """验证值可被 JSON 序列化"""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        raise ValueError("Expected a JSON-serializable value") from None

def _json_object(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("Expected a JSON object")
    return _json_value(value)


def _validate_json_value(value: Any) -> Any:
    return _json_value(value)


def _utc_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            # 3.11 以后兼容
            value = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError("Expected an ISO 8601 datetime with a timezone") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Expected a datetime with a timezone")
    return value.astimezone(UTC)

def unique_check(name: str):
    def check(value: list) -> list:
        if len(value) != len(set(value)):
            raise ValueError(f"{name} must be unique")
        else:
            return value
    return check


ID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
UTCDateTime = Annotated[datetime, BeforeValidator(_utc_datetime)]
Seconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]
JSONObject = Annotated[dict[str, Any], BeforeValidator(_json_object)]
JSONSchema = JSONObject
JSONValue = Annotated[Any, BeforeValidator(_validate_json_value)]
EnvironmentName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
NonNegativeInt = Annotated[int, Field(ge=0)]

ResourceKind = Literal["sources", "setters", "ai", "channels", "workflows"]
PluginKind = Literal["collector", "channel"]
SaveMode = Literal["create", "replace", "upsert"]
SourcePolicy = Literal["stop","notice", "skip"]
ContinuePolicy = Literal["stop", "continue"]
WorkflowStage = Literal["collect", "analyze", "aggregate", "notify", "finish"]
CollectionStatus = Literal["success", "empty", "filtered_empty", "missing", "failed", "timeout"]
AnalysisStatus = Literal["success", "failed", "timeout", "cancelled"]
DeliveryStatus = Literal["success", "failed", "timeout", "skipped"]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )


class ErrorInfo(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: JSONObject = Field(default_factory=dict)


class ValidationIssue(StrictModel):
    path: list[str | int]
    reason: str


class ErrorResponse(StrictModel):
    error: ErrorInfo


class SystemConfig(StrictModel):
    data_dir: str = "data"
    plugin_dir: str = "plugins"
    host: str = "127.0.0.1"
    port: int = Field(default=4300, ge=1, le=65535)
    # max_concurrent_runs: int = Field(default=4, ge=1)
    log_file: str | None = None
    master_key_env: EnvironmentName = "LOGAGENT_MASTER_KEY"
    master_key_file: str = "master.key"


class SourceConfig(StrictModel):
    id: ID
    collector: ID
    options: JSONObject = Field(default_factory=dict)
    setters: JSONObject = Field(default_factory=dict)
    template: ID | None = None
    timeout: Seconds = 60.0
    on_error: SourcePolicy = "notice"
    on_missing: SourcePolicy = "notice"
    on_empty: SourcePolicy = "notice"
    on_filtered_empty: SourcePolicy = "notice"


class SetterTemplate(StrictModel):
    id: ID
    collector: ID
    setters: JSONObject = Field(default_factory=dict)


class EnvironmentCredential(StrictModel):
    kind: Literal["env"] = "env"
    name: EnvironmentName


class EncryptedCredential(StrictModel):
    kind: Literal["encrypted"] = "encrypted"
    format_version: int = Field(default=1, ge=1, le=1)
    key_id: str = Field(min_length=1)
    ciphertext: str = Field(min_length=1)


Credential = Annotated[EnvironmentCredential | EncryptedCredential, Field(discriminator="kind")]


class AIConfig(StrictModel):
    id: ID
    provider: ID
    model: str = Field(min_length=1)
    base_url: str | None = None
    api_key: Credential | None = None
    system_prompt: str = ""
    model_options: JSONObject = Field(default_factory=dict)
    timeout: Seconds = 300.0
    retries: int = Field(default=3, ge=0)


class ChannelConfig(StrictModel):
    id: ID
    channel: ID
    options: JSONObject = Field(default_factory=dict)
    timeout: Seconds = 30.0
    enabled: bool = True


class AnalysisTask(StrictModel):
    id: ID
    ai: ID
    prompt: str = "{input}"


class FanInConfig(StrictModel):
    order: list[str] = Field(default_factory=list)
    separator: str = "\n\n"
    ai: ID | None = None
    prompt: str = "{input}"
    mark_incomplete: bool = True


class WorkflowDefinition(StrictModel):
    id: ID
    name: str = ""
    sources: Annotated[list[ID], AfterValidator(unique_check("sources IDs"))] = Field(min_length=1)
    analyses: list[AnalysisTask] = Field(min_length=1)
    fan_in: FanInConfig | None = None
    channels: Annotated[list[ID], AfterValidator(unique_check("channels IDs"))] = Field(default_factory=list)
    input_separator: str = "\n\n"
    include_counts: bool = False
    collection_concurrency: int = Field(default=4, ge=1)
    analysis_concurrency: int = Field(default=4, ge=1)
    on_all_empty: SourcePolicy = "stop"
    analysis_failure: ContinuePolicy = "continue"
    send_partial: bool = True
    interval_seconds: Seconds | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def valid_references(self) -> Self:
        tasks = [task.id for task in self.analyses]
        unique_check("analysis IDs")(tasks)
        if self.fan_in is not None:
            order = self.fan_in.order
            if len(order) != len(set(order)) or not set(order) <= {*tasks, "$input"}:
                raise ValueError("fan_in order must contain unique analysis IDs or $input")
        return self


class WorkflowSnapshot(StrictModel):
    workflow: WorkflowDefinition
    sources: dict[ID, SourceConfig]
    ai: dict[ID, AIConfig]
    channels: dict[ID, ChannelConfig]
    created_at: UTCDateTime

    @model_validator(mode="after")
    def exact_references(self) -> Self:
        # 验证引用完整性
        ai_ids = {task.ai for task in self.workflow.analyses}
        if self.workflow.fan_in is not None and self.workflow.fan_in.ai is not None:
            ai_ids.add(self.workflow.fan_in.ai)
        for resources, expected in (
            (self.sources, set(self.workflow.sources)),
            (self.ai, ai_ids),
            (self.channels, set(self.workflow.channels)),
        ):
            if set(resources) != expected or any(key != item.id for key, item in resources.items()):
                raise ValueError("Snapshot mappings must exactly cover their referenced IDs")
        return self


class CollectorOutput(StrictModel):
    status: CollectionStatus
    items: list[JSONObject] = Field(default_factory=list)
    text: str = ""
    count: NonNegativeInt = 0
    error: ErrorInfo | None = None
    metadata: JSONObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent_result(self) -> Self:
        if self.status == "success":
            if not self.text.strip() or self.count == 0 or self.error is not None:
                raise ValueError("Success requires consumable text, positive count and no error")
        else:
            if self.items or self.text or self.count:
                raise ValueError("Non-success results cannot expose consumable or unfinished data")
            if (self.status in ("empty", "filtered_empty")) != (self.error is None):
                raise ValueError("Only missing, failed and timeout results require an error")
        return self


class CollectionResult(CollectorOutput):
    source_id: ID


class AnalysisResult(StrictModel):
    task_id: ID
    status: AnalysisStatus
    text: str = ""
    error: ErrorInfo | None = None
    usage: JSONObject = Field(default_factory=dict)
    elapsed_ms: float = Field(default=0.0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def coherent_result(self) -> Self:
        if self.status == "success":
            if self.error is not None or not self.text.strip():
                raise ValueError("Successful analysis needs text and no error")
        elif self.text or self.error is None:
            raise ValueError("Unsuccessful analysis needs an error and cannot contain output text")
        return self


class Notification(StrictModel):
    session_id: ID
    output_id: ID
    title: str = ""
    text: str
    metadata: JSONObject = Field(default_factory=dict)


class DeliveryResult(StrictModel):
    channel_id: ID
    output_id: ID
    status: DeliveryStatus
    attempts: int = Field(ge=0, le=1)
    error: ErrorInfo | None = None


class PluginEntry(StrictModel):
    backend: str = Field(min_length=1)


class PluginManifest(StrictModel):
    id: ID
    version: str = Field(min_length=1)
    kind: PluginKind
    api_version: int = Field(ge=1, le=1)
    entry: PluginEntry


class PluginSettings(StrictModel):
    enabled: bool = True
    defaults: dict[ID, JSONObject] = Field(default_factory=dict)


PluginConfiguration = dict[PluginKind, dict[ID, PluginSettings]]


class CapabilityDescription(StrictModel):
    kind: PluginKind
    name: ID
    description: str = Field(min_length=1)
    plugin: str
    capabilities: list[str]
    options_schema: JSONSchema
    setters_schema: JSONSchema | None = None
    fields: list[str] = Field(default_factory=list)
    count_unit: str | None = None


class DiscoveryReport(StrictModel):
    registered: list[CapabilityDescription] = Field(default_factory=list)
    errors: list[ErrorInfo] = Field(default_factory=list)


class ExecutionContext(StrictModel):
    workflow_id: ID | None = None
    session_id: ID | None = None
    stage: WorkflowStage | None = None


@dataclass(frozen=True, slots=True)
class CollectionContext:
    """Invocation-only dependencies; absent optional services are diagnosed on use."""

    workflow_id: ID
    session_id: ID
    log_path: str | None = None
    credentials: CredentialResolver | None = None

    def __post_init__(self) -> None:
        try:
            # 因为是dataclass而非pydantic
            TypeAdapter(ID).validate_python(self.workflow_id)
            TypeAdapter(ID).validate_python(self.session_id)
        except Exception as exc:
            raise ValueError("workflow_id and session_id must be valid IDs") from exc
        if self.log_path is not None and not isinstance(self.log_path, str):
            raise ValueError("log_path must be a resolved path string")


class ComponentHealth(StrictModel):
    component: str
    status: Literal["available", "degraded", "unavailable", "unknown"]
    required: bool
    error: ErrorInfo | None = None
    checked_at: UTCDateTime | None = None


class HealthReport(StrictModel):
    status: Literal["ready", "degraded", "unavailable"]
    accepting_runs: bool
    checked_at: UTCDateTime
    components: list[ComponentHealth]


ModelT = TypeVar("ModelT", bound=StrictModel)


def copy_model(model: ModelT) -> ModelT:
    """Revalidate mutable nested data while producing an independent object."""
    return type(model).model_validate(deepcopy(model.model_dump(mode="python")))
