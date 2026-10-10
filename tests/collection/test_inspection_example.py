"""Verify the public inspection example against a small request database."""

import importlib.util
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "examples/workflows/axonhub-inspection/server.py"
_SPEC = importlib.util.spec_from_file_location("inspection_example", _SCRIPT)
inspection = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(inspection)


@pytest.fixture
def database(tmp_path):
    location = tmp_path / "axonhub.db"
    at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S") + ".000000000 +0000 UTC"
    with sqlite3.connect(location) as connection:
        connection.executescript("""
            CREATE TABLE requests(id INTEGER, model_id TEXT, status TEXT,
                                  metrics_latency_ms INTEGER, created_at TEXT);
            CREATE TABLE channels(id INTEGER, name TEXT);
            CREATE TABLE request_executions(id INTEGER, request_id INTEGER, channel_id INTEGER,
                model_id TEXT, error_message TEXT, response_status_code INTEGER,
                status TEXT, metrics_latency_ms INTEGER, created_at TEXT);
        """)
        connection.execute("INSERT INTO channels VALUES(1, 'upstream')")
        connection.executemany("INSERT INTO requests VALUES(?,?,?,?,?)", [
            (1, "model", "completed", 100, at),
            (2, "model", "failed", 200, at),
            (3, "model", "canceled", 300, at),
        ])
        connection.executemany("INSERT INTO request_executions VALUES(?,?,?,?,?,?,?,?,?)", [
            (1, 1, 1, "model", "timeout", 504, "failed", 100, at),
            (2, 2, 1, "model", "unavailable", 503, "failed", 200, at),
        ])
    return location


def test_failed_attempt_keeps_eventual_success_and_newest_first(database):
    result = inspection.recent_errors(database, 24, 1, ["request_id", "final_status", "error"])
    assert result["errors"] == [{"request_id": 2, "final_status": "failed", "error": "unavailable"}]
    assert result["coverage"]["failed_attempts"] == 2
    assert result["coverage"]["sample_truncated"] is True
    retry = inspection.recent_errors(database, 24, 2, ["request_id", "final_status"])
    assert retry["errors"][1]["final_status"] == "completed"


def test_status_counts_distinguish_cancel_and_failure(database):
    result = inspection.recent_activity(database, 24, 2)
    assert result["request_status_counts"] == {"canceled": 1, "completed": 1, "failed": 1}
    assert result["total_requests"] == 3
    assert [row["request_id"] for row in result["recent_requests"]] == [3, 2]


def test_database_is_read_only(database):
    with inspection.connect(database) as connection, pytest.raises(sqlite3.OperationalError):
        connection.execute("DELETE FROM requests")


def test_payload_and_credentials_are_excluded():
    message = '{"error":{"message":"Bearer private-key https://host/path?key=private"},"request_body":{"private":"data"}}'
    result = inspection.error_summary(message)
    assert "private" not in result
    assert "request_body" not in result
    assert "[redacted]" in result
    assert "[URL redacted]" in result
    assert "confidential" not in inspection.error_summary('error request_body={"messages":"confidential"}')
    assert inspection.error_summary("<html><title>Cloudflare Tunnel error</title><body>private payload</body></html>") == "HTML error page: Cloudflare Tunnel error"


@pytest.mark.parametrize("fields", [["request_body"], ["error", "error"], []])
def test_unknown_or_duplicate_fields_fail(database, fields):
    with pytest.raises(ValueError, match="fields"):
        inspection.recent_errors(database, 24, 5, fields)


@pytest.mark.parametrize("hours,limit", [(0, 1), (169, 1), (1, 0), (1, 101)])
def test_out_of_range_requests_fail(database, hours, limit):
    with pytest.raises(ValueError):
        inspection.recent_activity(database, hours, limit)
