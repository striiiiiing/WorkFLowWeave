"""Strict, JSON-compatible exchange models from the OpenSpec contracts.

Runtime dependencies live in CollectionContext, outside the serialized models.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from logagent.protocols import ArchiveReader, CredentialResolver


def _json_value(value: Any, ancestors: frozenset[int] = frozenset()) -> Any:
    """Reject coercion, non-finite numbers, non-string keys and cyclic objects."""
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) in (dict, list):
        if id(value) in ancestors:
            raise ValueError("JSON values must not contain cycles")
        nested = ancestors | {id(value)}
        if type(value) is list:
            return [_json_value(item, nested) for item in value]
        if any(type(key) is not str for key in value):
            raise ValueError("JSON object keys must be strings")
        return {key: _json_value(item, nested) for key, item in value.items()}
    raise ValueError("Expected a finite JSON value")


def _json_object(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("Expected a JSON object")
    return _json_value(value)


def _validate_json_value(value: Any) -> Any:
    return _json_value(value)


def _identifier(value: Any) -> str:
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) is None:
        raise ValueError("Expected an ID of 1-80 ASCII letters, digits, underscores or hyphens")
    return value


def _utc_datetime(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Expected an ISO 8601 datetime with a timezone") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Expected a datetime with a timezone")
    return value.astimezone(UTC)


ID = Annotated[str, BeforeValidator(_identifier)]
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
SourcePolicy = Literal["stop", "skip"]
ContinuePolicy = Literal["stop", "continue"]
ArtifactName = Literal["snapshot", "collection", "analysis", "final"]
WorkflowStage = Literal["collect", "analyze", "aggregate", "notify", "finish"]
CollectionStatus = Literal["success", "empty", "filtered_empty", "missing", "failed", "timeout"]
AnalysisStatus = Literal["success", "failed", "timeout", "cancelled"]
DeliveryStatus = Literal["success", "failed", "timeout", "skipped"]
SessionStatus = Literal[
    "created", "running", "completed", "partial", "failed", "cancelled", "interrupted"
]
MissingReason = Literal[
    "disabled", "out_of_scope", "not_created", "missing", "expired", "corrupt", "write_failed"
]
TERMINAL_SESSION_STATUSES = frozenset(
    {"completed", "partial", "failed", "cancelled", "interrupted"}
)
ARTIFACT_NAMES: tuple[ArtifactName, ...] = ("snapshot", "collection", "analysis", "final")


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        validate_assignment=True,
        revalidate_instances="always",
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
    port: int = Field(default=8000, ge=1, le=65535)
    max_concurrent_runs: int = Field(default=4, ge=1)
    log_file: str | None = None
    master_key_env: EnvironmentName = "LOGAGENT_MASTER_KEY"
    master_key_file: str = "master.key"


class SourceConfig(StrictModel):
    id: ID
    collector: ID
    options: JSONObject = Field(default_factory=dict)
    setters: JSONObject = Field(default_factory=dict)
    template: ID | None = None
    timeout: Seconds = 30.0
    on_error: SourcePolicy = "stop"
    on_missing: SourcePolicy = "stop"
    on_empty: SourcePolicy = "skip"
    on_filtered_empty: SourcePolicy = "skip"


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
    provider: ID = "mock"
    model: str = Field(default="mock", min_length=1)
    base_url: str | None = None
    api_key: Credential | None = None
    system_prompt: str = ""
    model_options: JSONObject = Field(default_factory=dict)
    timeout: Seconds = 60.0
    retries: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def reject_legacy_options(self) -> Self:
        if {"temperature", "top_k"}.intersection(self.model_options):
            raise ValueError("temperature and top_k are not supported")
        return self


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


class BackupPolicy(StrictModel):
    enabled: bool = True
    stages: list[ArtifactName] = Field(default_factory=lambda: list(ARTIFACT_NAMES))
    on_failure: ContinuePolicy = "stop"
    retention_days: Seconds | None = None

    @model_validator(mode="after")
    def unique_stages(self) -> Self:
        if len(self.stages) != len(set(self.stages)):
            raise ValueError("Backup stages must be unique")
        return self


class WorkflowDefinition(StrictModel):
    id: ID
    name: str = ""
    sources: list[ID] = Field(min_length=1)
    analyses: list[AnalysisTask] = Field(min_length=1)
    fan_in: FanInConfig | None = None
    channels: list[ID] = Field(default_factory=list)
    input_separator: str = "\n\n"
    include_counts: bool = False
    collection_concurrency: int = Field(default=4, ge=1)
    analysis_concurrency: int = Field(default=4, ge=1)
    on_all_empty: SourcePolicy = "stop"
    analysis_failure: ContinuePolicy = "continue"
    send_partial: bool = True
    backup: BackupPolicy = Field(default_factory=BackupPolicy)
    interval_seconds: Seconds | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def valid_references(self) -> Self:
        tasks = [task.id for task in self.analyses]
        for values in (self.sources, self.channels, tasks):
            if len(values) != len(set(values)):
                raise ValueError("Workflow references and analysis IDs must be unique")
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


class ArtifactInfo(StrictModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    size: NonNegativeInt
    written_at: UTCDateTime
    expires_at: UTCDateTime | None = None


class SessionRecord(StrictModel):
    id: ID
    workflow_id: ID
    status: SessionStatus = "created"
    created_at: UTCDateTime
    updated_at: UTCDateTime
    stage: WorkflowStage = "collect"
    source_statuses: dict[ID, CollectionStatus] = Field(default_factory=dict)
    analysis_statuses: dict[ID, AnalysisStatus] = Field(default_factory=dict)
    deliveries: list[DeliveryResult] = Field(default_factory=list)
    errors: list[ErrorInfo] = Field(default_factory=list)
    artifacts: dict[ArtifactName, ArtifactInfo] = Field(default_factory=dict)
    recoverable: bool = False
    missing_artifacts: dict[ArtifactName, MissingReason] = Field(default_factory=dict)
    output_frozen: bool = False

    @model_validator(mode="after")
    def coherent_record(self) -> Self:
        keys = [(delivery.output_id, delivery.channel_id) for delivery in self.deliveries]
        if len(keys) != len(set(keys)):
            raise ValueError("Delivery keys must be unique")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self


class CollectionArtifact(StrictModel):
    shared_input: str
    results: list[CollectionResult]

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        ids = [result.source_id for result in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("Collection source IDs must be unique")
        return self


class AnalysisArtifact(StrictModel):
    order: list[ID]
    results: list[AnalysisResult]

    @model_validator(mode="after")
    def valid_results(self) -> Self:
        ids = [result.task_id for result in self.results]
        if len(self.order) != len(set(self.order)) or len(ids) != len(set(ids)):
            raise ValueError("Analysis order and result IDs must be unique")
        if not set(ids) <= set(self.order):
            raise ValueError("Analysis result IDs must belong to order")
        return self


class FinalArtifact(StrictModel):
    outputs: list[Notification]
    fan_in: AnalysisResult | None = None

    @model_validator(mode="after")
    def unique_outputs(self) -> Self:
        ids = [output.output_id for output in self.outputs]
        sessions = {output.session_id for output in self.outputs}
        if len(ids) != len(set(ids)) or len(sessions) > 1:
            raise ValueError("Final outputs must have unique IDs and belong to one session")
        return self


ArtifactContent = WorkflowSnapshot | CollectionArtifact | AnalysisArtifact | FinalArtifact
ARTIFACT_MODELS: dict[ArtifactName, type[StrictModel]] = {
    "snapshot": WorkflowSnapshot,
    "collection": CollectionArtifact,
    "analysis": AnalysisArtifact,
    "final": FinalArtifact,
}


class ArtifactAvailability(StrictModel):
    available: list[ArtifactName]
    missing_artifacts: dict[ArtifactName, MissingReason]
    recoverable: bool


class ExpirationReport(StrictModel):
    sessions: NonNegativeInt
    artifacts: NonNegativeInt
    errors: list[JSONObject] = Field(default_factory=list)


class SessionArchiveEnvelope(StrictModel):
    format_version: int = Field(ge=1, le=1)
    backup: BackupPolicy
    record: SessionRecord
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)


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

    workflow_id: str
    session_id: str
    archive: ArchiveReader | None = None
    log_path: str | None = None
    credentials: CredentialResolver | None = None

    def __post_init__(self) -> None:
        _identifier(self.workflow_id)
        _identifier(self.session_id)
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
