"""Versioned compatibility at persisted-data boundaries; new API input stays strict."""

from copy import deepcopy
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from logagent.errors import LogAgentError

RESOURCE_FORMAT_VERSION = 4
LEGACY_SCHEDULE_FIELDS = {"interval_seconds", "cron", "cron_timezone"}


def migrate_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    """Convert legacy scheduling fields on one workflow snapshot or resource."""
    result = deepcopy(workflow)
    legacy = LEGACY_SCHEDULE_FIELDS & result.keys()
    if "schedule" in result and legacy:
        raise LogAgentError("invalid_config", "新旧 Workflow 调度字段冲突")
    if not legacy:
        return result
    interval = result.pop("interval_seconds", None)
    expression = result.pop("cron", None)
    timezone = result.pop("cron_timezone", "UTC")
    try:
        ZoneInfo(timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise LogAgentError("invalid_config", "旧 cron_timezone 必须为有效 IANA 时区") from None
    if interval is not None and expression is not None:
        raise LogAgentError("invalid_config", "旧 Workflow 间隔与 Cron 冲突")
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
        raise LogAgentError("invalid_config", "旧 Cron 必须为五段表达式")
    fields = expression.split()
    if fields[2] != "*" and fields[4] != "*":
        raise LogAgentError(
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
            raise LogAgentError("invalid_config", "旧 Cron 星期语法无法等价迁移") from None
        fields[4] = ",".join(dict.fromkeys(names[day] for day in sorted(days)))
    return " ".join(fields)


def _object(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise LogAgentError("invalid_config", f"旧资源 {name} 必须是对象")
    return value


def _input_prompt(value: Any) -> str:
    if not isinstance(value, str):
        raise LogAgentError("invalid_config", "旧 prompt 必须是字符串")
    return value if "{input}" in value else f"{value}\n\n{{input}}"


def _migrate_workflow_prompts(workflow: dict, ai: dict) -> None:
    analyses = workflow.get("analyses")
    if not isinstance(analyses, list):
        raise LogAgentError("invalid_config", "旧 Workflow analyses 必须是列表")
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
    if data.get("sources") or data.get("setters"):
        raise LogAgentError("collection_migration_required",
                            "旧 Collector/Setter 资源不兼容；请备份原文件并将来源重建为 MCP/CLI")
    result = deepcopy(data)
    result.pop("setters", None)
    result["mcp_servers"] = {}
    result["format_version"] = 4
    for workflow in result.get("workflows", {}).values():
        workflow.pop("include_counts", None)
    return result


_MIGRATIONS = {1: _migrate_v1_schedule, 2: _migrate_v2_prompts, 3: _migrate_v3_sources}


def migrate_resources(data: Any) -> tuple[Any, bool]:
    """Upgrade only stored versions; API payloads use current strict models."""
    if not isinstance(data, dict):
        return data, False
    changed = False
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
    if any("collector" in source for source in data.get("sources", {}).values()):
        raise LogAgentError("legacy_snapshot_incompatible", "旧 Collector 运行不能恢复执行；已有分析正文仍可读取")
    migrated = deepcopy(data)
    for channel in migrated.get("channels", {}).values():
        if isinstance(channel, dict) and channel.get("channel") == "mock":
            channel["channel"] = "file"
    workflow = migrated["workflow"]
    if LEGACY_SCHEDULE_FIELDS & workflow.keys():
        workflow = migrate_workflow(workflow)
        migrated["workflow"] = workflow
    analyses = workflow.get("analyses")
    fan_in = workflow.get("fan_in")
    has_legacy_prompt = any(isinstance(task, dict) and "prompt" in task for task in analyses or [])
    has_legacy_prompt |= isinstance(fan_in, dict) and "prompt" in fan_in
    if has_legacy_prompt:
        _migrate_workflow_prompts(workflow, _object(migrated.get("ai"), "ai"))
    return migrated
