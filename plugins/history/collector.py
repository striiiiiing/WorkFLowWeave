"""Read version-pinned session bodies exclusively through the injected reader."""

from __future__ import annotations

from datetime import UTC, datetime

import orjson

from logagent.errors import LogAgentError
from logagent.models import CollectionContext, CollectorOutput, ErrorInfo
from logagent.schema import validate_instance

_FIELDS = ["session_id", "workflow_id", "version", "created_at", "status", "content"]
_STAGES = ["collect", "analyze", "aggregate", "notify", "finish"]


def _time(value):
    if value is None:
        return None
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("Timezone required")
    return result.astimezone(UTC)


def _format(items, group_by):
    if group_by is None:
        return "\n".join(orjson.dumps(item).decode() for item in items)
    groups = {}
    for item in items:
        key = orjson.dumps(item.get(group_by)).decode()
        groups.setdefault(key, []).append(item)
    return "\n".join(orjson.dumps({"group_by": group_by, "value": orjson.loads(key),
                                 "items": values}).decode() for key, values in groups.items())


class HistoryCollector:
    name = "history"
    execution = "read"
    id_prefix = "history"
    description = "读取已存档的历史 session，不重新采集；正文固定到所选业务版本。"
    fields = _FIELDS
    count_unit = "sessions"
    options_schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "workflow_id": {"x-logagent-workflow": True, "type": ["string", "null"], "minLength": 1,
                            "description": "筛选 Workflow；省略查询所有 Workflow。"},
            "session_id": {"x-logagent-workflow": True, "type": ["string", "null"], "minLength": 1,
                           "description": "只读取指定 session，仍排除当前运行。"},
            "limit": {"x-logagent-workflow": True, "type": "integer", "minimum": 1, "maximum": 1000, "default": 10,
                      "description": "最近 session 数量，最多 1000，与 SessionReader 分页边界一致。"},
            "after": {"x-logagent-workflow": True, "type": ["string", "null"], "format": "date-time",
                      "description": "创建时间下界，含边界，必须有时区。"},
            "before": {"x-logagent-workflow": True, "type": ["string", "null"], "format": "date-time",
                       "description": "创建时间上界，含边界，必须有时区。"},
            "stages": {"x-logagent-workflow": True, "type": "array", "items": {"enum": _STAGES}, "uniqueItems": True,
                       "minItems": 1, "maxItems": 5, "default": ["collect"],
                       "description": "选择保存的阶段正文；默认采集阶段，避免重复拼入后续阶段。"},
            "max_tokens": {"x-logagent-workflow": True, "type": "integer", "minimum": 1, "maximum": 1048576,
                           "default": 8192, "description": "内容预算，使用每 UTF-8 字节一个估算 token 的保守计数，非模型 tokenizer。"},
            "overflow": {"x-logagent-workflow": True, "type": "string", "enum": ["truncate", "error"], "default": "error",
                         "description": "超预算拒绝，或仅保留能完整容纳的最新 session 前缀；至少须容纳一个。"},
        },
    }
    setters_schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "fields": {"type": "array", "items": {"enum": _FIELDS}, "uniqueItems": True,
                       "description": "显示字段，省略全部；空列表返回 filtered_empty。"},
            "group_by": {"type": ["string", "null"], "enum": ["workflow_id", "status", None],
                         "description": "按已选择字段分组；仍按 session 计数。"},
        },
    }

    def validate(self, options, setters):
        validate_instance(options, self.options_schema, path=["options"])
        validate_instance(setters, self.setters_schema, path=["setters"])
        for key in ("limit", "max_tokens"):
            if key in options and type(options[key]) is not int:
                raise LogAgentError("invalid_config", "历史数量及预算必须为整数")
        try:
            after, before = _time(options.get("after")), _time(options.get("before"))
            if after is not None and before is not None and after > before:
                raise ValueError("Invalid range")
        except ValueError:
            raise LogAgentError("invalid_config", "历史时间区间无效") from None
        if setters.get("group_by") and setters["group_by"] not in setters.get("fields", _FIELDS):
            raise LogAgentError("invalid_config", "历史分组字段必须包含在选择字段中")

    async def _select(self, reader, options, context):
        workflow = options.get("workflow_id")
        after, before = _time(options.get("after")), _time(options.get("before"))
        sid = options.get("session_id")
        if sid is None:
            return await reader.list_sessions(workflow, limit=options.get("limit", 10),
                                              after=after, before=before,
                                              exclude_session_id=context.session_id)
        if sid == context.session_id:
            return []
        try:
            record = await reader.get_session(sid)
        except LogAgentError as exc:
            if exc.code == "session_not_found":
                return []
            raise
        if ((workflow is not None and record.workflow_id != workflow)
                or (after is not None and record.created_at < after)
                or (before is not None and record.created_at > before)):
            return []
        return [record]

    async def collect(self, options, setters, context: CollectionContext):
        self.validate(options, setters)
        if context.session_reader is None:
            return CollectorOutput(status="missing", error=ErrorInfo(
                code="history_reader_missing", message="未注入只读历史查询接口"))
        metadata = {"count_unit": "sessions", "budget_method": "utf8_bytes_upper_estimate",
                    "max_tokens": options.get("max_tokens", 8192), "truncated": False}
        try:
            selected = await self._select(context.session_reader, options, context)
            metadata["selected"] = [{"session_id": r.session_id, "version": r.version} for r in selected]
            if not selected:
                return CollectorOutput(status="empty", metadata=metadata)
            fields = setters.get("fields", _FIELDS)
            if not fields:
                return CollectorOutput(status="filtered_empty", metadata=metadata)
            items = []
            for index, record in enumerate(selected):
                content = {}
                if "content" in fields:
                    for stage in options.get("stages", ["collect"]):
                        phase = await context.session_reader.get_phase_content(
                            record.session_id, stage, version=record.version)
                        if phase.availability != "available":
                            return CollectorOutput(
                                status="failed" if phase.availability == "corrupt" else "missing",
                                error=ErrorInfo(code="history_content_unavailable", message="所选历史正文不可用",
                                                details={"session_id": record.session_id, "version": record.version,
                                                         "stage": stage, "availability": phase.availability}),
                                metadata=metadata)
                        content[stage] = phase.content
                item = {**record.model_dump(mode="json"), "content": content}
                items.append({key: item[key] for key in fields})
                text = _format(items, setters.get("group_by"))
                if len(text.encode("utf-8")) <= metadata["max_tokens"]:
                    continue
                items.pop()
                if options.get("overflow", "error") == "error" or not items:
                    return CollectorOutput(status="failed", error=ErrorInfo(
                        code="history_budget_exceeded", message="历史正文超过预算，未返回不完整内容"), metadata=metadata)
                metadata["truncated"] = True
                metadata["omitted"] = metadata["selected"][index:]
                break
            text = _format(items, setters.get("group_by"))
            metadata["estimated_tokens"] = len(text.encode("utf-8"))
            metadata["included"] = metadata["selected"][:len(items)]
            return CollectorOutput(status="success", text=text, items=items, count=len(items), metadata=metadata)
        except LogAgentError as exc:
            return CollectorOutput(status="missing" if exc.code in {
                "session_not_found", "version_not_found", "content_unavailable"
            } else "failed", error=ErrorInfo(
                code="history_read_failed", message="历史读取失败",
                details={"cause": exc.code}), metadata=metadata)
