"""Decode persisted snapshots without changing their stored bytes or new input rules."""

from typing import Any

from workflowweave.config.migrations import migrate_legacy_snapshot
from workflowweave.models import WorkflowSnapshot


def parse_historical_snapshot(data: Any) -> WorkflowSnapshot:
    return WorkflowSnapshot.model_validate(
        migrate_legacy_snapshot(data), context={"historical_snapshot": True},
    )
