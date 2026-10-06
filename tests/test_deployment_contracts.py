"""Remote frontend/backend deployment boundary contracts."""

from __future__ import annotations

import pytest

from workflowweave.deployment import RemoteBackendOrigin, validate_terminal_snapshot
from workflowweave.errors import WorkFLowWeaveError


def test_remote_backend_origin_has_no_embedded_credentials():
    origin = RemoteBackendOrigin.parse("https://workflow.example.test:4300/api/")

    assert origin.base_url == "https://workflow.example.test:4300/api"
    assert origin.host == "workflow.example.test"

    with pytest.raises(WorkFLowWeaveError, match="凭据"):
        RemoteBackendOrigin.parse("https://user:secret@workflow.example.test")


@pytest.mark.parametrize("value", ["workflow.example.test", "ftp://workflow.example.test", ""])
def test_remote_backend_origin_rejects_unsafe_or_ambiguous_urls(value):
    with pytest.raises(WorkFLowWeaveError, match="地址"):
        RemoteBackendOrigin.parse(value)


def test_terminal_snapshot_must_match_session_and_terminal_status():
    snapshot = {
        "session_id": "session-1",
        "version": 4,
        "status": "completed",
        "workflow_id": "daily",
    }

    assert validate_terminal_snapshot(snapshot, session_id="session-1") is True

    with pytest.raises(WorkFLowWeaveError):
        validate_terminal_snapshot({**snapshot, "session_id": "other"}, session_id="session-1")
    with pytest.raises(WorkFLowWeaveError):
        validate_terminal_snapshot({**snapshot, "status": "running"}, session_id="session-1")
