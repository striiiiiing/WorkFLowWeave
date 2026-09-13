"""Collect existing terminal session content through the read-only archive API."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError

from logagent.errors import LogAgentError, exception_error
from logagent.models import (
    ARTIFACT_MODELS,
    ID,
    TERMINAL_SESSION_STATUSES,
    AnalysisArtifact,
    ArtifactContent,
    ArtifactName,
    CollectionArtifact,
    CollectionContext,
    CollectorOutput,
    ErrorInfo,
    FinalArtifact,
    JSONObject,
    SessionRecord,
    UTCDateTime,
)
from logagent.schema import schema_defaults, validate_instance, validate_schema

_ID = TypeAdapter(ID)
_TIME = TypeAdapter(UTCDateTime)
_SCHEMA_VERSION = "https://json-schema.org/draft/2020-12/schema"
_OPTIONS_SCHEMA = {
    "$schema": _SCHEMA_VERSION,
    "type": "object",
    "description": "按时间及最近次数读取历史；预算固定以 utf8_bytes_v1 计算最终文本 UTF-8 字节数，不是模型实际 token 数。",
    "properties": {
        "workflow_id": {
            "type": "string",
            "description": "待读取的既有 Workflow 标识；不触发该 Workflow。",
            "pattern": "^[A-Za-z0-9_-]{1,80}$",
            "minLength": 1,
            "maxLength": 80,
        },
        "artifact": {
            "type": "string",
            "description": "读取 collection 共享输入、analysis 成功分支或 final 已冻结输出。",
            "enum": ["collection", "analysis", "final"],
            "default": "final",
        },
        "limit": {
            "type": "integer",
            "description": "时间窗口内最近的终态运行次数；按创建时间及 ID 倒序选择。",
            "minimum": 1,
            "default": 1,
        },
        "start_time": {
            "type": "string",
            "description": "包含边界的创建时间下限，使用带时区的 RFC 3339 时间。",
            "format": "date-time",
        },
        "end_time": {
            "type": "string",
            "description": "包含边界的创建时间上限，使用带时区的 RFC 3339 时间。",
            "format": "date-time",
        },
        "token_budget": {
            "type": "integer",
            "description": "非负预算，使用 utf8_bytes_v1 统计最终文本（包括来源标记及分隔符）的 UTF-8 字节；0 不保留记录。",
            "minimum": 0,
        },
        "overflow": {
            "type": "string",
            "description": "truncate 只保留最新完整记录前缀；error 在超预算时报告失败。",
            "enum": ["truncate", "error"],
            "default": "truncate",
        },
    },
    "required": ["workflow_id"],
    "additionalProperties": False,
}
_SETTERS_SCHEMA = {
    "$schema": _SCHEMA_VERSION,
    "type": "object",
    "description": "历史来源暂不提供额外 Setter；阶段投影和完整记录预算由 options 明确选择。",
    "properties": {},
    "additionalProperties": False,
}
_MISSING_REASONS = frozenset(
    {"disabled", "out_of_scope", "not_created", "missing", "expired", "write_failed"}
)
_SAFE_CAUSES = frozenset(
    {
        "size_limit",
        "integrity_mismatch",
        "snapshot_mismatch",
        "invalid_content",
        "unsafe_path",
        "changed_during_read",
        "not_regular",
        "unfrozen",
    }
)
_SEPARATOR = "\n\n"


def _time(value: str | None) -> datetime | None:
    return None if value is None else _TIME.validate_python(value)


class HistoryCollector:
    name = "history"
    description = "只读既有终态运行的阶段正文，按时间、次数和完整记录预算选择。"
    count_unit = "records"

    def __init__(self) -> None:
        self.fields: list[str] = []
        self.options_schema = deepcopy(_OPTIONS_SCHEMA)
        self.setters_schema = deepcopy(_SETTERS_SCHEMA)
        validate_schema(self.options_schema)
        validate_schema(self.setters_schema)

    def validate(self, options: JSONObject, setters: JSONObject) -> None:
        """Pure validation, also usable when the collector is called directly."""
        validate_instance(options, self.options_schema, path=["options"])
        validate_instance(setters, self.setters_schema, path=["setters"])
        try:
            _ID.validate_python(options["workflow_id"])
        except ValidationError:
            raise LogAgentError(
                "invalid_config",
                "历史 Workflow 标识格式无效",
                {"errors": [{"path": ["options", "workflow_id"], "reason": "invalid_id"}]},
            ) from None
        for name in ("limit", "token_budget"):
            if name in options and type(options[name]) is not int:
                raise LogAgentError(
                    "invalid_config",
                    "历史次数和预算必须为整数",
                    {"errors": [{"path": ["options", name], "reason": "strict_integer"}]},
                )
        times = {}
        for name in ("start_time", "end_time"):
            try:
                times[name] = _time(options.get(name))
            except ValidationError:
                raise LogAgentError(
                    "invalid_config",
                    "历史时间必须为合法的带时区时间",
                    {"errors": [{"path": ["options", name], "reason": "invalid_datetime"}]},
                ) from None
        start, end = times["start_time"], times["end_time"]
        if start is not None and end is not None and start > end:
            raise LogAgentError(
                "invalid_config",
                "历史时间范围的起点不能晚于终点",
                {"errors": [{"path": ["options", "start_time"], "reason": "after_end_time"}]},
            )

    async def collect(
        self, options: JSONObject, setters: JSONObject, context: CollectionContext
    ) -> CollectorOutput:
        self.validate(options, setters)
        values = {**schema_defaults(self.options_schema), **options}
        artifact_name: ArtifactName = values["artifact"]
        budget = values.get("token_budget")
        metadata: JSONObject = {
            "artifact": artifact_name,
            "budget_algorithm": "utf8_bytes_v1",
            "token_budget": budget,
            "used_bytes": 0,
            "truncated": False,
        }
        if context.archive is None:
            return CollectorOutput(
                status="missing",
                error=ErrorInfo(
                    code="history_archive_missing",
                    message="历史来源未注入只读存档能力",
                    details={"reason": "missing", "artifact": artifact_name},
                ),
                metadata=metadata,
            )
        start = _time(values.get("start_time"))
        end = _time(values.get("end_time"))
        current_record: SessionRecord | None = None
        try:
            # Filtering precedes the recent-count limit. An API/default list
            # limit must not conceal older matches in the requested window.
            candidates = await context.archive.list(values["workflow_id"], limit=None)
            candidates = [
                record
                for record in candidates
                if record.workflow_id == values["workflow_id"]
                and record.id != context.session_id
                and record.status in TERMINAL_SESSION_STATUSES
                and (start is None or record.created_at >= start)
                and (end is None or record.created_at <= end)
            ]
            candidates.sort(key=lambda record: (record.created_at, record.id), reverse=True)
            selected = candidates[: values["limit"]]
            if not selected:
                return CollectorOutput(status="empty", metadata=metadata)
            items: list[JSONObject] = []
            texts: list[str] = []
            used_bytes = 0
            for current_record in selected:
                if artifact_name == "final" and not current_record.output_frozen:
                    raise LogAgentError(
                        "artifact_unavailable",
                        "历史最终输出尚未冻结",
                        {
                            "session_id": current_record.id,
                            "artifact": "final",
                            "reason": "not_created",
                            "cause": "unfrozen",
                        },
                    )
                content = await context.archive.load_artifact(current_record.id, artifact_name)
                text = self._extract_text(content, artifact_name, current_record.id)
                if not text.strip():
                    continue
                created = current_record.created_at.isoformat().replace("+00:00", "Z")
                formatted = (
                    f"[history workflow={current_record.workflow_id} session={current_record.id} "
                    f"created_at={created} artifact={artifact_name}]\n{text}"
                )
                next_bytes = used_bytes + len(formatted.encode("utf-8"))
                if texts:
                    next_bytes += len(_SEPARATOR.encode("utf-8"))
                if budget is not None and next_bytes > budget:
                    if values["overflow"] == "error":
                        return CollectorOutput(
                            status="failed",
                            error=ErrorInfo(
                                code="history_budget_exceeded",
                                message="完整历史记录超过配置预算",
                                details={
                                    "session_id": current_record.id,
                                    "artifact": artifact_name,
                                    "token_budget": budget,
                                    "required_bytes": next_bytes,
                                },
                            ),
                            metadata=metadata,
                        )
                    metadata["truncated"] = True
                    break
                items.append(
                    {
                        "session_id": current_record.id,
                        "workflow_id": current_record.workflow_id,
                        "created_at": created,
                        "artifact": artifact_name,
                        "text": text,
                    }
                )
                texts.append(formatted)
                used_bytes = next_bytes
            metadata["used_bytes"] = used_bytes
            if not items:
                return CollectorOutput(status="filtered_empty", metadata=metadata)
            return CollectorOutput(
                status="success",
                items=items,
                text=_SEPARATOR.join(texts),
                count=len(items),
                metadata=metadata,
            )
        except LogAgentError as exc:
            reason = exc.details.get("reason")
            if not isinstance(reason, str):
                reason = None
            missing = reason in _MISSING_REASONS or exc.code == "session_not_found"
            details: JSONObject = {"artifact": artifact_name}
            if current_record is not None:
                details["session_id"] = current_record.id
            if reason in {*_MISSING_REASONS, "corrupt"}:
                details["reason"] = reason
            cause = exc.details.get("cause")
            if isinstance(cause, str) and cause in _SAFE_CAUSES:
                details["cause"] = cause
            return CollectorOutput(
                status="missing" if missing else "failed",
                error=ErrorInfo(code=exc.code, message="无法读取选中的历史正文", details=details),
                metadata=metadata,
            )
        except Exception as exc:
            details: dict[str, Any] = {"artifact": artifact_name}
            if current_record is not None:
                details["session_id"] = current_record.id
            return CollectorOutput(
                status="failed",
                error=exception_error(
                    exc, code="history_read_failed", message="历史读取失败", details=details
                ),
                metadata=metadata,
            )

    @staticmethod
    def _extract_text(content: ArtifactContent, name: ArtifactName, session_id: str) -> str:
        try:
            content = ARTIFACT_MODELS[name].model_validate(content)
        except ValidationError:
            raise LogAgentError(
                "artifact_unavailable", "历史正文结构损坏", {"reason": "corrupt"}
            ) from None
        if isinstance(content, CollectionArtifact):
            return content.shared_input
        if isinstance(content, AnalysisArtifact):
            results = {result.task_id: result for result in content.results}
            return _SEPARATOR.join(
                f"[analysis task={task_id}]\n{results[task_id].text}"
                for task_id in content.order
                if task_id in results and results[task_id].status == "success"
            )
        if isinstance(content, FinalArtifact):
            if any(output.session_id != session_id for output in content.outputs):
                raise LogAgentError(
                    "artifact_unavailable", "历史输出归属错误", {"reason": "corrupt"}
                )
            return _SEPARATOR.join(
                f"[output id={output.output_id}]\n{output.text}"
                for output in content.outputs
                if output.text.strip()
            )
        raise LogAgentError("artifact_unavailable", "不支持的历史正文类型", {"reason": "corrupt"})
