"""The shared APScheduler interpretation used by validation, preview and execution."""

import calendar
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from cron_descriptor import ExpressionDescriptor, Options


def cron_trigger(expression: str, timezone: str | None = None) -> CronTrigger:
    if len(expression.split()) != 5:
        raise ValueError("Cron must be a five-field expression")
    try:
        zone = ZoneInfo(timezone) if timezone is not None else None
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("timezone must be a valid IANA timezone") from None
    trigger = CronTrigger.from_crontab(expression, timezone=zone)
    if trigger.get_next_fire_time(None, datetime.now(UTC)) is None:
        raise ValueError("Cron has no future occurrence")
    return trigger


def describe_cron(expression: str, trigger: CronTrigger) -> str:
    options = Options(use_24hour_time_format=True, locale_code="zh_CN")
    fields = expression.split()
    names = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    # Expand using APScheduler itself, preserving step/range semantics as well as weekdays.
    if fields[4] != "*":
        weekday = trigger.fields[4]
        monday = datetime(2026, 9, 28, tzinfo=UTC)
        fields[4] = ",".join(
            names[day]
            for day in range(7)
            if weekday.get_next_value(monday + timedelta(days=day)) == day
        )
    description = ExpressionDescriptor(" ".join(fields), options).get_description()
    weekday_names = dict(
        zip(
            calendar.day_name,
            (
                "星期一",
                "星期二",
                "星期三",
                "星期四",
                "星期五",
                "星期六",
                "星期日",
            ),
            strict=True,
        )
    )
    weekday_pattern = "|".join(rf"(?<!\w){re.escape(name)}(?!\w)" for name in weekday_names)
    return re.sub(weekday_pattern, lambda match: weekday_names[match.group()], description)
