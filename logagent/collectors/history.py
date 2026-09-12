"""Read complete archived records without executing their original sources."""

import logging
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from logagent._io import run_io
from logagent.errors import LogAgentError
from logagent.models import (
    AnalysisResult,
    CollectionResult,
    Identifier,
    Model,
    Notification,
    PositiveInt,
    SessionRecord,
    SessionStatus,
    unique,
    validate_json_value,
)

from .base import BaseCollector, CollectionContext
from .setters import CommonSetters

logger = logging.getLogger(__name__)
_TERMINAL = {
    SessionStatus.COMPLETED,
    SessionStatus.PARTIAL,
    SessionStatus.FAILED,
    SessionStatus.CANCELLED,
    SessionStatus.INTERRUPTED,
}
_MISSING_REASONS = {"disabled", "out_of_scope", "not_created", "missing", "expired"}


class HistoryOptions(Model):
    workflow_id: Identifier
    stages: Annotated[list[Literal["collection", "analysis", "final"]], Field(min_length=1, strict=True)] = Field(
        default_factory=lambda: ["final"]
    )
    last_n: PositiveInt | None = None
    since: datetime | None = None
    until: datetime | None = None
    max_tokens: PositiveInt | None = None
    token_counter: Literal["utf8_bytes"] = "utf8_bytes"
    overflow: Literal["truncate", "error"] | None = Field(default=None, validate_default=True)

    @field_validator("stages")
    @classmethod
    def stages_unique(cls, value):
        return unique(value, "stages")

    @field_validator("since", "until", mode="before")
    @classmethod
    def iso_timestamps(cls, value):
        if value is None or isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise ValueError("Expected an ISO 8601 timestamp with a timezone")

    @field_validator("overflow")
    @classmethod
    def explicit_overflow(cls, value, info: ValidationInfo):
        if info.data.get("max_tokens") is not None and value is None:
            raise ValueError("overflow must be specified when max_tokens is set")
        return value

    @model_validator(mode="after")
    def ordered_time_range(self):
        if self.since is not None and self.until is not None and self.since >= self.until:
            raise ValueError("since must be earlier than until")
        return self


def _archive_failure(
    error: Exception, workflow_id: str, *, session_id: str | None = None, stage: str | None = None
) -> LogAgentError:
    reason = "archive_unavailable"
    missing = False
    if isinstance(error, LogAgentError):
        if error.code in {"ARTIFACT_UNAVAILABLE", "ARCHIVE_ARTIFACT_UNAVAILABLE"}:
            reported = error.details.get("reason")
            if reported in _MISSING_REASONS | {"corrupt", "write_failed"}:
                reason = reported
                missing = reported in _MISSING_REASONS
        elif error.code == "NOT_FOUND" and session_id is not None:
            reason, missing = "session_missing", True
    details = {"workflow_id": workflow_id, "reason": reason}
    if session_id is not None:
        details["session_id"] = session_id
    if stage is not None:
        details["stage"] = stage
    return LogAgentError(
        "COLLECTOR_MISSING" if missing else "COLLECTOR_FAILED",
        "Required history content is unavailable" if missing else "The history archive could not be read",
        details,
    )


def _stage_records(session: SessionRecord, stage: str, content: dict) -> list[dict]:
    """Validate a reader's public payload and retain its declared result order."""
    expected = {
        "collection": {"shared_input", "results"},
        "analysis": {"order", "results", "events"},
        "final": {"outputs", "fan_in"},
    }
    validate_json_value(content)
    if not isinstance(content, dict) or set(content) != expected[stage]:
        raise ValueError("Invalid stage structure")
    common = {
        "workflow_id": session.workflow_id,
        "session_id": session.id,
        "created_at": session.model_dump(mode="json", include={"created_at"})["created_at"],
        "stage": stage,
    }
    if stage == "collection":
        if not isinstance(content["shared_input"], str) or not isinstance(content["results"], list):
            raise ValueError("Invalid collection structure")
        results = [CollectionResult.model_validate(value) for value in content["results"]]
        unique([result.source_id for result in results], "collection.results")
        return [{**common, "output_id": "collection", "text": content["shared_input"]}]
    if stage == "analysis":
        order, values, events = content["order"], content["results"], content["events"]
        if (
            not isinstance(order, list)
            or not all(isinstance(value, str) for value in order)
            or not isinstance(values, list)
            or not isinstance(events, list)
            or not all(isinstance(value, dict) for value in events)
        ):
            raise ValueError("Invalid analysis structure")
        results = [AnalysisResult.model_validate(value) for value in values]
        unique(order, "analysis.order")
        unique([result.task_id for result in results], "analysis.results")
        by_id = {result.task_id: result for result in results}
        if set(by_id) - set(order):
            raise ValueError("Analysis results do not match their declared order")
        return [
            {**common, "output_id": task_id, "text": by_id[task_id].text, "status": by_id[task_id].status.value}
            for task_id in order
            if task_id in by_id
        ]
    if not isinstance(content["outputs"], list):
        raise TypeError("Invalid final structure")
    outputs = [Notification.model_validate(value) for value in content["outputs"]]
    unique([output.output_id for output in outputs], "final.outputs")
    if any(output.session_id != session.id for output in outputs):
        raise ValueError("Final output belongs to a different session")
    if content["fan_in"] is not None:
        AnalysisResult.model_validate(content["fan_in"])
    return [{**common, "output_id": output.output_id, "text": output.text} for output in outputs]


class HistoryCollector(BaseCollector):
    name = "history"
    description = "Collect existing Workflow history within explicit session, time and content budgets."
    options_model = HistoryOptions
    setters_model = CommonSetters
    fields = ("workflow_id", "session_id", "created_at", "stage", "output_id", "text", "status")

    def _select(self, groups: list[list[dict]], options: HistoryOptions) -> tuple[list[dict], dict]:
        costs = [[len(self.format_item(item).encode("utf-8")) for item in group] for group in groups]
        count = sum(map(len, groups))
        total = sum(sum(group) for group in costs) + max(0, count - 1)
        exceeded = options.max_tokens is not None and total > options.max_tokens and options.overflow == "error"
        diagnostics = {
            "token_counter": options.token_counter,
            "max_tokens": options.max_tokens,
            "candidate_records": count,
            "candidate_tokens": total,
            "selected_records": 0,
            "used_tokens": 0,
            "truncated": False,
            "limit_exceeded": exceeded,
        }
        if exceeded:
            return [], diagnostics
        chosen = []
        full = False
        for group, group_costs in zip(groups, costs, strict=True):
            selected = []
            for item, item_cost in zip(group, group_costs, strict=True):
                cost = item_cost + bool(diagnostics["selected_records"])
                if options.max_tokens is not None and diagnostics["used_tokens"] + cost > options.max_tokens:
                    full = True
                    break
                selected.append(item)
                diagnostics["used_tokens"] += cost
                diagnostics["selected_records"] += 1
            chosen.append(selected)
            if full:
                break
        diagnostics["truncated"] = diagnostics["selected_records"] < count
        # Reverse session groups, never stage or branch order within a session.
        return [item for group in reversed(chosen) for item in group], diagnostics

    async def collect(
        self, options: HistoryOptions, setters: CommonSetters, context: CollectionContext
    ) -> list[dict]:
        if context.archive is None:
            raise _archive_failure(RuntimeError(), options.workflow_id)
        try:
            values = await context.archive.list(workflow_id=options.workflow_id, limit=None)
            if not isinstance(values, list):
                raise TypeError("Invalid history listing")
            sessions = [SessionRecord.model_validate(value) for value in values]
        except Exception as exc:
            raise _archive_failure(exc, options.workflow_id) from exc
        sessions = [
            session
            for session in sessions
            if session.workflow_id == options.workflow_id
            and session.status in _TERMINAL
            and session.id != context.session_id
            and (options.since is None or session.created_at >= options.since)
            and (options.until is None or session.created_at < options.until)
        ]
        sessions.sort(key=lambda session: (session.created_at, session.id), reverse=True)
        if options.last_n is not None:
            sessions = sessions[: options.last_n]
        groups = []
        for session in sessions:
            records = []
            for stage in options.stages:
                try:
                    content = await context.archive.load_artifact(session.id, stage)
                except Exception as exc:
                    raise _archive_failure(exc, options.workflow_id, session_id=session.id, stage=stage) from exc
                try:
                    records.extend(await run_io(_stage_records, session, stage, content))
                except (ValueError, TypeError, KeyError) as exc:
                    raise LogAgentError(
                        "COLLECTOR_FAILED",
                        "The archived stage has an invalid structure",
                        {"workflow_id": options.workflow_id, "session_id": session.id, "stage": stage, "reason": "corrupt"},
                    ) from exc
            groups.append(records)
        try:
            items, diagnostics = await run_io(self._select, groups, options)
        except UnicodeError as exc:
            raise LogAgentError(
                "COLLECTOR_FAILED", "History content is not valid UTF-8", {"reason": "corrupt"}
            ) from exc
        context.metadata["history"] = diagnostics
        if diagnostics["limit_exceeded"]:
            raise LogAgentError(
                "HISTORY_TOKEN_LIMIT",
                "The candidate history exceeds its configured content budget",
                {
                    "max_tokens": options.max_tokens,
                    "actual_tokens": diagnostics["candidate_tokens"],
                    "token_counter": options.token_counter,
                },
            )
        if diagnostics["truncated"]:
            logger.info(
                "History budget selected %s of %s complete records",
                diagnostics["selected_records"],
                diagnostics["candidate_records"],
                extra={
                    "workflow_id": context.workflow_id,
                    "session_id": context.session_id,
                    "collector": self.name,
                    "history": diagnostics,
                },
            )
        return items
