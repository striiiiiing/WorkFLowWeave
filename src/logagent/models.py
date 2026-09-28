"""JSON-compatible exchange models derived from the approved module designs.

Runtime dependencies live in CollectionContext, outside the serialized models.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self, TypeVar

import orjson
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    model_validator,
)

from logagent.scheduling import cron_trigger

if TYPE_CHECKING:
    from logagent.protocols import CredentialResolver, SessionReader

_JSON_VALUE = TypeAdapter(JsonValue, config=ConfigDict(strict=True, allow_inf_nan=False))


def _json_value(value: Any) -> Any:
    """Validate JSON types and round-trip through orjson for an independent value."""
    try:
        return orjson.loads(orjson.dumps(_JSON_VALUE.validate_python(value)))
    except (ValueError, orjson.JSONEncodeError):
        raise ValueError("Expected a JSON-compatible value supported by orjson") from None


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
# Leave space for an underscore and the 36-character UUID in generated resource IDs.
ResourceIDPrefix = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,43}$")]
UTCDateTime = Annotated[datetime, BeforeValidator(_utc_datetime)]
Seconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]
JSONObject = Annotated[dict[str, Any], BeforeValidator(_json_object)]
JSONSchema = JSONObject
JSONValue = Annotated[Any, BeforeValidator(_validate_json_value)]
EnvironmentName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
SessionVersion = Annotated[int, Field(gt=0)]

ResourceKind = Literal["sources", "setters", "ai", "channels", "workflows"]
PluginKind = Literal["collector", "channel", "tool"]
SaveMode = Literal["create", "replace", "upsert"]
SourcePolicy = Literal["stop","notice", "skip"]
ContinuePolicy = Literal["stop", "continue"]
WorkflowStage = Literal["collect", "analyze", "aggregate", "notify", "finish"]
CollectionStatus = Literal["success", "empty", "filtered_empty", "missing", "failed", "timeout"]
AnalysisStatus = Literal["success", "failed", "timeout", "cancelled"]
DeliveryStatus = Literal["success", "failed", "timeout", "skipped"]
SessionStatus = Literal[
    "created", "running", "completed", "partial", "failed", "cancelled", "interrupted"
]
ArtifactAvailability = Literal[
    "available", "pending", "not_saved", "expired", "missing", "corrupt", "write_failed"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=False
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
    max_concurrent_runs: int = Field(default=4, ge=1)
    log_file: str | None = None
    master_key_env: EnvironmentName = "LOGAGENT_MASTER_KEY"
    master_key_file: str = "master.key"


class SourceConfig(StrictModel):
    id: ID
    display_name: str | None = None
    description: str = ""
    collector: ID
    enabled: bool = True
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


ModelName = Annotated[str, Field(min_length=1, pattern=r"\S")]


class AIConfig(StrictModel):
    id: ID
    provider: ID
    base_url: str | None = None
    api_key: Credential | None = None
    system_prompt: str = ""
    models: dict[ModelName, JSONObject] = Field(default_factory=dict)
    timeout: Seconds = 600.0
    retries: int = Field(default=5, ge=0)

class ChannelConfig(StrictModel):
    id: ID
    channel: ID
    options: JSONObject = Field(default_factory=dict)
    timeout: Seconds = 30.0
    enabled: bool = True
    agent_enabled: bool = False


class AnalysisTask(StrictModel):
    id: ID
    ai: ID
    system_prompt: str | None = None
    input_prompt: str | None = None
    user_prompt: str = ""
    model: ModelName


class FanInConfig(StrictModel):
    order: list[str] = Field(default_factory=list)
    separator: str = "\n\n"
    ai: ID | None = None
    system_prompt: str | None = None
    input_prompt: str | None = None
    user_prompt: str = ""
    reuse_from: ID | Literal["$first"] | None = "$first"
    model: ModelName | None = None
    mark_incomplete: bool = True

    def ordered_inputs(self, analyses: list[AnalysisTask]) -> list[str]:
        return self.order or ["$input", *(task.id for task in analyses)]

    def reused_task(self, analyses: list[AnalysisTask]) -> AnalysisTask | None:
        if self.reuse_from is None:
            return None
        if self.reuse_from == "$first":
            return analyses[0]
        return next(task for task in analyses if task.id == self.reuse_from)

    @model_validator(mode="after")
    def paired_model(self) -> Self:
        if (self.ai is None) != (self.model is None):
            raise ValueError("Fan-in AI and model must be specified together")
        if self.reuse_from is not None and self.ai is not None:
            raise ValueError("Fan-in model reuse and explicit AI/model are mutually exclusive")
        return self


class BackupPolicy(StrictModel):
    """Retention policy for business content and any persisted execution copies."""

    enabled: bool = True
    snapshot: bool = True
    collection: bool = True
    analysis: bool = True
    final: bool = True
    on_failure: ContinuePolicy = "stop"
    retention_days: int | None = Field(default=None, gt=0)


class SourceOverride(StrictModel):
    source: SourceConfig | None = None
    options: JSONObject = Field(default_factory=dict)
    setters: JSONObject = Field(default_factory=dict)
    template: ID | None = None

    @model_validator(mode="after")
    def detached_source_has_no_template(self) -> Self:
        if self.source is not None and (
            self.source.template is not None or self.template is not None
        ):
            raise ValueError("Detached source snapshots cannot reference setter templates")
        return self


class ChannelOverride(StrictModel):
    options: JSONObject = Field(default_factory=dict)


class AtSchedule(StrictModel):
    type: Literal["at"]
    at: UTCDateTime


class EverySchedule(StrictModel):
    type: Literal["every"]
    every_seconds: Seconds


class CronSchedule(StrictModel):
    type: Literal["cron"]
    expression: str
    timezone: str | None = None

    @model_validator(mode="after")
    def valid_cron(self) -> Self:
        cron_trigger(self.expression, self.timezone)
        return self


WorkflowSchedule = Annotated[AtSchedule | EverySchedule | CronSchedule, Field(discriminator="type")]


class WorkflowDefinition(StrictModel):
    id: ID
    name: str = ""
    sources: Annotated[list[ID], AfterValidator(unique_check("sources IDs"))] = Field(min_length=1)
    analyses: list[AnalysisTask] = Field(min_length=1)
    fan_in: FanInConfig | None = None
    system_prompt: str = ""
    input_prompt: str = "{input}"
    channels: Annotated[list[ID], AfterValidator(unique_check("channels IDs"))] = Field(default_factory=list)
    source_overrides: dict[ID, SourceOverride] = Field(default_factory=dict)
    channel_overrides: dict[ID, ChannelOverride] = Field(default_factory=dict)
    input_separator: str = "\n\n"
    include_counts: bool = True
    collection_concurrency: int = Field(default=4, ge=1)
    analysis_concurrency: int = Field(default=4, ge=1)
    on_all_empty: SourcePolicy = "stop"
    analysis_failure: ContinuePolicy = "continue"
    send_partial: bool = True
    schedule: WorkflowSchedule | None = None
    enabled: bool = True
    backup: BackupPolicy = Field(default_factory=BackupPolicy)

    @model_validator(mode="after")
    def valid_references(self) -> Self:
        if not self.source_overrides.keys() <= set(self.sources):
            raise ValueError("Source overrides must reference selected sources")
        if any(
            override.source is not None and override.source.id != ident
            for ident, override in self.source_overrides.items()
        ):
            raise ValueError("Detached source IDs must match their workflow binding")
        if not self.channel_overrides.keys() <= set(self.channels):
            raise ValueError("Channel overrides must reference selected channels")
        tasks = [task.id for task in self.analyses]
        unique_check("analysis IDs")(tasks)
        if self.fan_in is not None:
            order = self.fan_in.order
            if len(order) != len(set(order)) or not set(order) <= {*tasks, "$input"}:
                raise ValueError("fan_in order must contain unique analysis IDs or $input")
            if self.fan_in.reuse_from not in {None, "$first", *tasks}:
                raise ValueError("fan_in reuse_from must reference an analysis task or $first")
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
        for task in self.workflow.analyses:
            selected = task.model
            if selected not in self.ai[task.ai].models:
                raise ValueError("Analysis task model is not configured")
        if self.workflow.fan_in and self.workflow.fan_in.ai:
            selected = self.workflow.fan_in.model
            if selected not in self.ai[self.workflow.fan_in.ai].models:
                raise ValueError("Fan-in model is not configured")
        return self


class ReportText(StrictModel):
    kind: Literal["text"]
    title: str = Field(min_length=1)
    text: str


class ReportMetric(StrictModel):
    label: str = Field(min_length=1)
    value: str | Annotated[int, Field(strict=True)] | Annotated[float, Field(strict=True, allow_inf_nan=False)]
    unit: str = ""


class ReportMetrics(StrictModel):
    kind: Literal["metrics"]
    title: str = Field(min_length=1)
    items: list[ReportMetric]


class ReportTable(StrictModel):
    kind: Literal["table"]
    title: str = Field(min_length=1)
    columns: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    rows: list[list[str | Annotated[int, Field(strict=True)] | Annotated[float, Field(strict=True, allow_inf_nan=False)] | bool | None]]

    @model_validator(mode="after")
    def matching_columns(self) -> Self:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Report table rows must match the declared columns")
        return self


class ResultReport(StrictModel):
    sections: list[Annotated[ReportText | ReportMetrics | ReportTable, Field(discriminator="kind")]]


class CollectorOutput(StrictModel):
    status: CollectionStatus
    items: list[JSONObject] = Field(default_factory=list)
    text: str = ""
    count: NonNegativeInt = 0
    error: ErrorInfo | None = None
    metadata: JSONObject = Field(default_factory=dict)
    report: ResultReport | None = None

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

    @model_validator(mode="after")
    def coherent_result(self) -> Self:
        if self.status == "success" and (self.attempts != 1 or self.error is not None):
            raise ValueError("Successful delivery requires one attempt and no error")
        if self.status == "skipped" and (self.attempts != 0 or self.error is not None):
            raise ValueError("Skipped delivery requires zero attempts and no error")
        if self.status in ("failed", "timeout") and self.error is None:
            raise ValueError("Failed or timed out delivery requires an error")
        return self


class ArtifactInfo(StrictModel):
    stage: WorkflowStage
    availability: ArtifactAvailability
    size_bytes: NonNegativeInt | None = None
    error: ErrorInfo | None = None


class PhaseContent(ArtifactInfo):
    """A body read from one explicitly selected SessionStore version."""

    session_id: ID
    version: SessionVersion
    content: JSONValue = None

    @model_validator(mode="after")
    def coherent_content(self) -> Self:
        if (self.availability == "available") != (self.content is not None):
            raise ValueError("Only available phase content carries a non-null body")
        return self


class RecoveryAvailability(StrictModel):
    available: bool
    reason: ErrorInfo | None = None


class WorkflowProgress(StrictModel):
    """已提交业务结果的轻量引用，不包含正文或运行配置。"""

    session_id: ID
    execution_epoch: str | None = None
    stage: WorkflowStage | None = None
    event: Literal["item", "aggregate", "delivery", "lifecycle"]
    status: str
    item_id: ID | None = None
    output_id: ID | None = None
    channel_id: ID | None = None
    label: str | None = None
    result_ref: str | None = None
    version: SessionVersion | None = None
    availability: ArtifactAvailability = "pending"
    error: ErrorInfo | None = None
    summary: JSONObject = Field(default_factory=dict)


class SessionRecord(StrictModel):
    """Read-only business session data, independent of execution checkpoints."""

    session_id: ID
    workflow_id: ID
    workflow_name: str | None = None
    version: SessionVersion
    status: SessionStatus
    stage: WorkflowStage | None = None
    created_at: UTCDateTime
    updated_at: UTCDateTime
    finished_at: UTCDateTime | None = None
    error: ErrorInfo | None = None
    artifacts: list[ArtifactInfo] = Field(default_factory=list)
    snapshot_availability: ArtifactAvailability
    execution_epoch: str | None = None
    progress: list[WorkflowProgress] = Field(default_factory=list)


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


PluginConfiguration = dict[PluginKind, dict[ID, PluginSettings]]


class CapabilityDescription(StrictModel):
    kind: PluginKind
    name: ID
    id_prefix: ResourceIDPrefix | None = None
    description: str = Field(min_length=1)
    plugin: str
    capabilities: list[str]
    options_schema: JSONSchema
    setters_schema: JSONSchema | None = None
    fields: list[str] = Field(default_factory=list)
    count_unit: str | None = None
    input_schema: JSONSchema | None = None
    execution: Literal["read", "exclusive"] = "exclusive"


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
    session_reader: SessionReader | None = None

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
