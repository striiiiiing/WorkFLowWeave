"""跨模块 session、历史与投递数据契约测试。

通过真实 Pydantic 模型和参数矩阵检查备份默认值、保留期限、业务版本、
投递状态/次数/错误组合，以及正文为空与不可用的区别。断言非法组合被拒绝，
运行期 SessionReader 不进入持久配置；不涉及数据库或真实投递。
"""

from datetime import UTC, datetime
from itertools import product

import pytest
from pydantic import ValidationError

from workflowweave.models import (
    ArtifactInfo,
    BackupPolicy,
    CollectionContext,
    DeliveryResult,
    ErrorInfo,
    PhaseContent,
    SessionRecord,
    SourceConfig,
    SystemConfig,
    WorkflowDefinition,
)
from workflowweave.protocols import SessionReader


def test_workflow_defaults_keep_every_phase_and_snapshot_without_expiry():
    workflow = WorkflowDefinition(
        id="workflow", sources=["source"], analyses=[{"user_prompt": "analyze input", "id": "analysis", "ai": "ai", "model": "model"}]
    )
    assert workflow.backup.enabled
    assert workflow.backup.snapshot
    assert workflow.backup.collection and workflow.backup.analysis and workflow.backup.final
    assert workflow.backup.checkpoint_retention_days == 7
    assert workflow.backup.collection_retention_days == 30
    assert workflow.backup.analysis_retention_days is None
    assert workflow.backup.final_retention_days is None
    assert workflow.backup.on_failure == "stop"
    copied = WorkflowDefinition.model_validate_json(workflow.model_dump_json())
    assert copied == workflow
    copied.backup.collection = False
    assert workflow.backup.collection
    assert not BackupPolicy(enabled=False).enabled


@pytest.mark.parametrize("days", [0, -1, 1.5, "invalid"])
@pytest.mark.parametrize("field", ["checkpoint", "collection", "analysis", "final"])
def test_backup_rejects_invalid_retention(days, field):
    with pytest.raises(ValidationError):
        BackupPolicy(**{f"{field}_retention_days": days})


def test_new_configuration_preserves_coercion_and_rejects_unknown_fields():
    assert BackupPolicy(collection_retention_days="7").collection_retention_days == 7
    assert BackupPolicy(checkpoint_retention_days=30, collection_retention_days=1,
                        analysis_retention_days=7, final_retention_days=2)
    assert SystemConfig().max_concurrent_runs == 4
    assert SystemConfig(max_concurrent_runs="2").max_concurrent_runs == 2
    for data in ({"max_concurrent_runs": 0}, {"unknown": True}):
        with pytest.raises(ValidationError):
            SystemConfig(**data)
    for data in ({"on_failure": "bogus"}, {"extra": 1}, {"retention_days": 7}):
        with pytest.raises(ValidationError):
            BackupPolicy(**data)


@pytest.mark.parametrize(
    ("status", "attempts", "has_error"),
    list(product(["success", "skipped", "failed", "timeout"], [0, 1, 2], [False, True])),
)
def test_delivery_status_attempt_and_error_matrix(status, attempts, has_error):
    error = ErrorInfo(code="delivery_failed", message="Delivery failed") if has_error else None
    data = dict(
        channel_id="channel", output_id="output", status=status, attempts=attempts, error=error
    )
    valid = (
        (status == "success" and attempts == 1 and not has_error)
        or (status == "skipped" and attempts == 0 and not has_error)
        or (status in ("failed", "timeout") and attempts in (0, 1) and has_error)
    )
    if valid:
        receipt = DeliveryResult(**data)
        assert DeliveryResult.model_validate_json(receipt.model_dump_json()) == receipt
    else:
        with pytest.raises(ValidationError):
            DeliveryResult(**data)


@pytest.mark.parametrize("body", ["", [], {}, {"text": "已保存正文", "count": 1}])
def test_available_empty_content_is_distinct_from_unavailable_content(body):
    content = PhaseContent(
        session_id="session", version=1, stage="collect",
        availability="available", content=body,
    )
    assert PhaseContent.model_validate_json(content.model_dump_json()) == content
    with pytest.raises(ValidationError):
        PhaseContent.model_validate({**content.model_dump(), "availability": "expired"})


@pytest.mark.parametrize(
    "availability", ["pending", "not_saved", "expired", "missing", "corrupt", "write_failed"]
)
def test_unavailable_content_preserves_the_reason(availability):
    content = PhaseContent(
        session_id="session", version=1, stage="analyze",
        availability=availability,
    )
    assert content.content is None
    assert content.model_dump()["availability"] == availability


def test_phase_content_rejects_missing_body_and_non_json_data():
    data = dict(
        session_id="session", version=1, stage="collect",
        availability="available",
    )
    for body in (None, {"items": (1, 2)}, {"when": datetime.now(UTC)}, {"value": float("nan")}):
        with pytest.raises(ValidationError):
            PhaseContent(**data, content=body)
    with pytest.raises(ValidationError):
        PhaseContent(**{**data, "version": 0}, content="text")


def test_session_has_pinned_business_version_and_separate_body_availability():
    record = SessionRecord(
        session_id="session", workflow_id="workflow", version=1,
        status="interrupted", stage="analyze", created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC), snapshot_availability="available",
        artifacts=[ArtifactInfo(stage="collect", availability="expired")],
    )
    assert SessionRecord.model_validate_json(record.model_dump_json()) == record
    assert "content" not in record.model_dump()["artifacts"][0]


@pytest.mark.parametrize("version", [0, -1, 1.5, "checkpoint-1", None])
@pytest.mark.parametrize("model", [SessionRecord, PhaseContent])
def test_session_version_requires_a_positive_integer(model, version):
    data = dict(session_id="session", version=version, stage="collect")
    if model is SessionRecord:
        data.update(
            workflow_id="workflow", status="running", created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC), snapshot_availability="available",
        )
    else:
        data.update(availability="available", content={"text": "saved"})
    with pytest.raises(ValidationError):
        model(**data)


def test_business_version_preserves_coercion_and_rejects_checkpoint_identifiers():
    data = dict(
        session_id="session", version="2", stage="collect",
        availability="available", content={"text": "saved"},
    )
    assert PhaseContent(**data).version == 2
    with pytest.raises(ValidationError):
        PhaseContent(**data, checkpoint_id="checkpoint-1")


def test_session_reader_is_injected_only_as_a_runtime_dependency():
    class Reader:
        async def get_session(self, session_id, *, version=None):
            raise NotImplementedError

        async def list_sessions(self, workflow_id=None, **kwargs):
            raise NotImplementedError

        async def get_phase_content(self, session_id, stage, *, version):
            raise NotImplementedError

    reader: SessionReader = Reader()
    context = CollectionContext(
        workflow_id="workflow", session_id="session", session_reader=reader
    )
    assert context.session_reader is reader
    assert not hasattr(context, "model_dump")
    with pytest.raises(ValidationError):
        SourceConfig(id="source", call={"kind": "mcp", "server": "server", "tool": "history", "arguments": {"context": context}})
