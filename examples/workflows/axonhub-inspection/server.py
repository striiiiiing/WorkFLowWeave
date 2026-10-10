# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==1.30.0"]
# ///
"""Read-only AxonHub request inspection through Streamable HTTP MCP."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

Hours = Annotated[int, Field(ge=1, le=168)]
Limit = Annotated[int, Field(ge=1, le=100)]
ErrorField = Literal[
    "request_id", "application", "channel", "model", "error", "http_status",
    "attempt_status", "final_status", "latency_ms", "at",
]
DEFAULT_ERROR_FIELDS = [
    "request_id", "application", "channel", "model", "error", "http_status",
    "attempt_status", "final_status", "at",
]
ERROR_CHAR_LIMIT = 1200
QUERY_TIMEOUT_SECONDS = 10
SECRET_PATTERNS = (
    (re.compile(r"\b(?:sk|ghp|gho|github_pat)-?[A-Za-z0-9_-]{16,}\b"), "[redacted]"),
    (re.compile(r"(?i)\bBearer\s+\S+"), "Bearer [redacted]"),
    (re.compile(r'(?i)([\"\']?(?:api[_-]?key|authorization|access[_-]?token|password|secret)[\"\']?\s*[:=]\s*)[\"\']?[^\s,}\"\']+'), r"\1[redacted]"),
    (re.compile(r"https?://[^\s\"'<>]+"), "[URL redacted]"),
)


def error_summary(value: str | None) -> str:
    """Keep an upstream message, excluding payloads, credentials and URLs."""
    text = value or ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error", parsed)
        if isinstance(error, dict):
            text = json.dumps(
                {key: error[key] for key in ("type", "code", "message") if key in error},
                ensure_ascii=False,
            )
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    if title:
        text = "HTML error page: " + re.sub(r"\s+", " ", title.group(1)).strip()
    # Upstream failures may append a serialized request to their message.
    text = re.split(r"(?i)\b(?:request_body|response_body|request_headers|messages)\s*[:=]", text)[0]
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[:ERROR_CHAR_LIMIT]


@contextmanager
def connect(database: Path):
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    deadline = datetime.now(UTC) + timedelta(seconds=QUERY_TIMEOUT_SECONDS)
    connection.set_progress_handler(lambda: int(datetime.now(UTC) > deadline), 10000)
    try:
        yield connection
    finally:
        connection.close()


def window_start(hours: int) -> str:
    if type(hours) is not int or not 1 <= hours <= 168:
        raise ValueError("hours must be an integer between 1 and 168")
    # AxonHub stores UTC timestamps as 'YYYY-MM-DD HH:MM:SS.fraction +0000 UTC'.
    return (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def validate_limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")


def recent_errors(database: Path, hours: int, limit: int, fields: list[str]) -> dict:
    validate_limit(limit)
    if not fields or len(fields) != len(set(fields)) or not set(fields) <= set(ErrorField.__args__):
        raise ValueError("fields must be unique names from the error field allowlist")
    since = window_start(hours)
    with connect(database) as connection:
        rows = connection.execute(
            """SELECT e.request_id, c.name AS channel, e.model_id AS model,
                      e.error_message AS error, e.response_status_code AS http_status,
                      e.status AS attempt_status, r.status AS final_status,
                      e.metrics_latency_ms AS latency_ms, e.created_at AS at
               FROM request_executions e
               JOIN requests r ON r.id = e.request_id
               LEFT JOIN channels c ON c.id = e.channel_id
               WHERE e.created_at >= ? AND e.status = 'failed'
               ORDER BY e.created_at DESC, e.id DESC LIMIT ?""",
            (since, limit),
        ).fetchall()
        counts = dict(connection.execute(
            "SELECT status,count(*) FROM request_executions WHERE created_at>=? GROUP BY status",
            (since,),
        ).fetchall())
    items = []
    for row in rows:
        item = {**dict(row), "application": "axonhub", "error": error_summary(row["error"])}
        items.append({key: item[key] for key in fields})
    return {
        "errors": items,
        "coverage": {
            "window_start_utc": since, "window_hours": hours,
            "failed_attempts": counts.get("failed", 0), "sampled_attempts": len(items),
            "sample_limit": limit, "sample_truncated": counts.get("failed", 0) > len(items),
            "note": "Failed attempts include retries; final_status is the client request outcome.",
        },
    }


def recent_activity(database: Path, hours: int, limit: int) -> dict:
    validate_limit(limit)
    since = window_start(hours)
    with connect(database) as connection:
        statuses = dict(connection.execute(
            "SELECT status,count(*) FROM requests WHERE created_at>=? GROUP BY status", (since,),
        ).fetchall())
        by_model = [dict(row) for row in connection.execute(
            """SELECT model_id AS model, status, count(*) AS requests
               FROM requests WHERE created_at>=? GROUP BY model_id,status
               ORDER BY requests DESC,model_id,status LIMIT 100""", (since,),
        )]
        latest = [dict(row) for row in connection.execute(
            """SELECT id AS request_id,model_id AS model,status,metrics_latency_ms AS latency_ms,
                      created_at AS at FROM requests WHERE created_at>=?
               ORDER BY created_at DESC,id DESC LIMIT ?""", (since, limit),
        )]
    return {
        "window_start_utc": since, "window_hours": hours, "request_status_counts": statuses,
        "total_requests": sum(statuses.values()),
        "by_model": by_model, "model_group_limit": 100,
        "recent_requests": latest, "recent_sample_limit": limit,
        "note": "Counts cover requests created in the window. Samples are newest first; canceled is distinct from failed.",
    }


def create_server(database: Path, port: int) -> FastMCP:
    server = FastMCP(
        "AxonHub inspection", host="127.0.0.1", port=port,
        stateless_http=True, json_response=True,
    )

    @server.tool()
    def axonhub_recent_errors(
        hours: Hours = 24, limit: Limit = 60,
        fields: list[ErrorField] | None = None,
    ) -> dict:
        """Read recent failed attempts, safe error fields and eventual request outcomes."""
        return recent_errors(database, hours, limit, DEFAULT_ERROR_FIELDS if fields is None else fields)

    @server.tool()
    def axonhub_recent_activity(hours: Hours = 24, limit: Limit = 30) -> dict:
        """Read full-window request status counts and recent request samples."""
        return recent_activity(database, hours, limit)

    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--port", type=int, default=19036)
    arguments = parser.parse_args()
    if not arguments.database.is_file():
        parser.error("AxonHub database does not exist")
    create_server(arguments.database, arguments.port).run(transport="streamable-http")
