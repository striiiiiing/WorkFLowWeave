"""Explicit compatibility at persisted-data boundaries; new API input stays strict."""

from copy import deepcopy
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from logagent.errors import LogAgentError

LEGACY_SCHEDULE_FIELDS = {"interval_seconds", "cron", "cron_timezone"}


def migrate_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
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


def migrate_resources(data: Any) -> Any:
    if not isinstance(data, dict) or data.get("format_version") != 1:
        return data
    result = deepcopy(data)
    if isinstance(result.get("workflows"), dict):
        result["workflows"] = {
            key: migrate_workflow(value) if isinstance(value, dict) else value
            for key, value in result["workflows"].items()
        }
    result["format_version"] = 2
    return result
