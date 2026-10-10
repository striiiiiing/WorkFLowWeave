"""Versioned compatibility at persisted-data boundaries; new API input stays strict."""

from copy import deepcopy
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from workflowweave.ai.options import OPENAI_COMPATIBLE_PROVIDER
from workflowweave.errors import WorkFLowWeaveError

RESOURCE_FORMAT_VERSION = 4
LEGACY_SCHEDULE_FIELDS = {"interval_seconds", "cron", "cron_timezone"}
_RETIRED_SOURCE_DEFAULTS = {
    "collector": None,
    "options": {},
    "setters": {},
    "template": None,
    "on_missing": "notice",
    "on_filtered_empty": "notice",
}


def migrate_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    """Convert legacy scheduling fields on one workflow snapshot or resource."""
    result = deepcopy(workflow)
    legacy = LEGACY_SCHEDULE_FIELDS & result.keys()
    if "schedule" in result and legacy:
        raise WorkFLowWeaveError("invalid_config", "新旧 Workflow 调度字段冲突")
    if not legacy:
        return result
    interval = result.pop("interval_seconds", None)
    expression = result.pop("cron", None)
    timezone = result.pop("cron_timezone", "UTC")
    try:
        ZoneInfo(timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise WorkFLowWeaveError("invalid_config", "旧 cron_timezone 必须为有效 IANA 时区") from None
    if interval is not None and expression is not None:
        raise WorkFLowWeaveError("invalid_config", "旧 Workflow 间隔与 Cron 冲突")
    result["schedule"] = None
    if interval is not None:
        result["schedule"] = {"type": "every", "every_seconds": interval}
    if expression is not None:
        result["schedule"] = {
            "type": "cron", "expression": _legacy_cron(expression), "timezone": timezone,
        }
    return result


def _legacy_cron(expression: str) -> str:
    if not isinstance(expression, str) or len(expression.split()) != 5:
        raise WorkFLowWeaveError("invalid_config", "旧 Cron 必须为五段表达式")
    fields = expression.split()
    if fields[2] != "*" and fields[4] != "*":
        raise WorkFLowWeaveError(
            "invalid_config", "旧 Cron 同时约束日期和星期，无法保留 OR 语义；请显式重设计划",
        )
    if fields[4] != "*":
        # Expand legacy numeric ranges/steps before converting Sunday=0/7 to names.
        names = ("sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun")
        days: set[int] = set()
        try:
            for part in fields[4].lower().split(","):
                base, *step_parts = part.split("/")
                step = int(step_parts[0]) if step_parts else 1
                if len(step_parts) > 1 or step <= 0:
                    raise ValueError
                if base == "*":
                    start, end = 0, 6
                elif "-" in base:
                    left, right = base.split("-")
                    start = names.index(left) if left in names else int(left)
                    end = names.index(right) if right in names else int(right)
                else:
                    start = names.index(base) if base in names else int(base)
                    if step_parts and start == 7:
                        start = 0
                    end = 6 if step_parts else start
                if not (0 <= start <= 7 and 0 <= end <= 7):
                    raise ValueError
                if end < start:
                    end += 7
                days.update(day % 7 for day in range(start, end + 1, step))
        except (ValueError, IndexError):
            raise WorkFLowWeaveError("invalid_config", "旧 Cron 星期语法无法等价迁移") from None
        fields[4] = ",".join(dict.fromkeys(names[day] for day in sorted(days)))
    return " ".join(fields)


def _object(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise WorkFLowWeaveError("invalid_config", f"旧资源 {name} 必须是对象")
    return value


def _input_prompt(value: Any) -> str:
    if not isinstance(value, str):
        raise WorkFLowWeaveError("invalid_config", "旧 prompt 必须是字符串")
    return value if "{input}" in value else f"{value}\n\n{{input}}"


def _migrate_workflow_prompts(workflow: dict, ai: dict) -> None:
    """Upgrade editable resources without discarding user-supplied overrides."""
    analyses = workflow.get("analyses")
    if not isinstance(analyses, list):
        raise WorkFLowWeaveError("invalid_config", "旧 Workflow analyses 必须是列表")
    workflow.setdefault("system_prompt", "")
    workflow.setdefault("input_prompt", "{input}")
    for task in analyses:
        task = _object(task, "analysis")
        config = _object(ai.get(task.get("ai")), "analysis AI")
        task.setdefault("system_prompt", config.get("system_prompt", ""))
        _migrate_resource_prompt(task, required=True)
    fan_in = workflow.get("fan_in")
    if fan_in is None:
        return
    fan_in = _object(fan_in, "fan_in")
    if fan_in.get("ai") is not None:
        config = _object(ai.get(fan_in["ai"]), "fan_in AI")
        fan_in.setdefault("system_prompt", config.get("system_prompt", ""))
    fan_in.setdefault("reuse_from", None)
    fan_in.setdefault("single_task_optimization", False)
    _migrate_resource_prompt(
        fan_in, required=fan_in.get("ai") is not None or fan_in.get("reuse_from") is not None,
    )
    if not fan_in.get("order"):
        fan_in["order"] = [task.get("id") for task in analyses]


def _migrate_resource_prompt(item: dict, *, required: bool) -> None:
    legacy = item.pop("prompt", "{input}")
    if not isinstance(legacy, str):
        raise WorkFLowWeaveError("invalid_config", "旧 prompt 必须是字符串")
    item.setdefault("input_prompt", "{input}")
    item.setdefault("user_prompt", legacy.replace("{input}", "").strip())
    difference = item["user_prompt"]
    if required and (not isinstance(difference, str) or not difference.strip()):
        raise WorkFLowWeaveError(
            "prompt_migration_required", "旧任务没有可迁移的差异指令，请补齐 user_prompt",
        )


def _migrate_historical_prompts(workflow: dict, ai: dict) -> None:
    """Historical runs retain their original two-message request semantics."""
    analyses = workflow.get("analyses")
    if not isinstance(analyses, list):
        raise WorkFLowWeaveError("invalid_config", "旧 Workflow analyses 必须是列表")
    workflow["system_prompt"] = ""
    workflow["input_prompt"] = "{input}"
    for task in analyses:
        task = _object(task, "analysis")
        config = _object(ai.get(task.get("ai")), "analysis AI")
        task["system_prompt"] = config.get("system_prompt", "")
        task["input_prompt"] = _input_prompt(task.pop("prompt", "{input}"))
        task["user_prompt"] = ""
    fan_in = workflow.get("fan_in")
    if fan_in is not None:
        fan_in = _object(fan_in, "fan_in")
        if fan_in.get("ai") is not None:
            config = _object(ai.get(fan_in["ai"]), "fan_in AI")
            fan_in["system_prompt"] = config.get("system_prompt", "")
        fan_in["input_prompt"] = _input_prompt(fan_in.pop("prompt", "{input}"))
        fan_in["user_prompt"] = ""
        fan_in["reuse_from"] = None
        if fan_in.get("order", []) == []:
            fan_in["order"] = [task.get("id") for task in analyses]


def _migrate_v1_schedule(data: dict) -> dict:
    migrated = deepcopy(data)
    workflows = migrated.get("workflows")
    if isinstance(workflows, dict):
        migrated["workflows"] = {
            key: migrate_workflow(value) if isinstance(value, dict) else value
            for key, value in workflows.items()
        }
    migrated["format_version"] = 2
    return migrated


def _migrate_v2_prompts(data: dict) -> dict:
    migrated = deepcopy(data)
    ai = _object(migrated.get("ai"), "ai")
    workflows = _object(migrated.get("workflows"), "workflows")
    for value in workflows.values():
        _migrate_workflow_prompts(_object(value, "workflow"), ai)
    migrated["format_version"] = 3
    return migrated


def _migrate_v3_sources(data):
    result = deepcopy(data)
    result.setdefault("mcp_servers", {})
    result["format_version"] = 4
    return result


_MIGRATIONS = {1: _migrate_v1_schedule, 2: _migrate_v2_prompts, 3: _migrate_v3_sources}


def _normalize_providers(data: dict) -> tuple[dict, bool]:
    ai = data.get("ai")
    if not isinstance(ai, dict) or not any(
        isinstance(value, dict) and value.get("provider") == "http"
        for value in ai.values()
    ):
        return data, False
    result = deepcopy(data)
    for value in result["ai"].values():
        if isinstance(value, dict) and value.get("provider") == "http":
            value["provider"] = OPENAI_COMPATIBLE_PROVIDER
    return result, True


def migrate_resources(data: Any) -> tuple[Any, bool]:
    """Upgrade only stored versions; API payloads use current strict models."""
    if not isinstance(data, dict):
        return data, False
    data, changed = _normalize_providers(data)
    version = data.get("format_version")
    while type(version) is int and version in _MIGRATIONS:
        data = _MIGRATIONS[version](data)
        changed = True
        version = data["format_version"]
    # The resource shape is unchanged: this is a persisted capability rename,
    # not an alias accepted by new API input. Keep IDs, paths and bindings.
    channels = data.get("channels")
    if isinstance(channels, dict) and any(
        isinstance(value, dict) and value.get("channel") == "mock"
        for value in channels.values()
    ):
        data = deepcopy(data)
        for value in data["channels"].values():
            if isinstance(value, dict) and value.get("channel") == "mock":
                value["channel"] = "file"
        changed = True
    return data, changed


def migrate_legacy_snapshot(data: Any) -> Any:
    """Read old session archives without accepting legacy fields in new API requests."""
    if not isinstance(data, dict) or not isinstance(data.get("workflow"), dict):
        return data
    migrated, _ = _normalize_providers(deepcopy(data))
    for channel in migrated.get("channels", {}).values():
        if isinstance(channel, dict) and channel.get("channel") == "mock":
            channel["channel"] = "file"
    workflow = migrated["workflow"]
    if type(workflow.get("include_counts")) is bool:
        workflow.pop("include_counts")
    sources = list(migrated.get("sources", {}).values())
    for override in workflow.get("source_overrides", {}).values():
        if isinstance(override, dict) and isinstance(override.get("source"), dict):
            sources.append(override["source"])
    for source in sources:
        if not isinstance(source, dict):
            continue
        call = source.get("call")
        if not isinstance(call, dict) or call.get("kind") not in {"mcp", "cli"}:
            continue
        # Early MCP/CLI snapshots serialized unused Collector defaults. Keep
        # non-default values so strict validation exposes unsupported semantics.
        for field, default in _RETIRED_SOURCE_DEFAULTS.items():
            if field in source and type(source[field]) is type(default) and source[field] == default:
                source.pop(field)
    if LEGACY_SCHEDULE_FIELDS & workflow.keys():
        workflow = migrate_workflow(workflow)
        migrated["workflow"] = workflow
    analyses = workflow.get("analyses")
    fan_in = workflow.get("fan_in")
    has_legacy_prompt = any(isinstance(task, dict) and "prompt" in task for task in analyses or [])
    has_legacy_prompt |= isinstance(fan_in, dict) and "prompt" in fan_in
    if has_legacy_prompt:
        _migrate_historical_prompts(workflow, _object(migrated.get("ai"), "ai"))
    return migrated
