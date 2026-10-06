"""Workflow 数据保留策略；默认值来自 redesign-workflow design §5.4。"""

from datetime import UTC, datetime, timedelta
from typing import Literal

import orjson
from pydantic import Field
from sqlmodel import select

from workflowweave.model_base import StrictModel


class BackupPolicy(StrictModel):
    """Retention policy for business content and any persisted execution copies."""

    enabled: bool = True
    snapshot: bool = True
    collection: bool = True
    analysis: bool = True
    final: bool = True
    on_failure: Literal["stop", "continue"] = "stop"
    checkpoint_retention_days: int | None = Field(default=7, gt=0)
    collection_retention_days: int | None = Field(default=30, gt=0)
    analysis_retention_days: int | None = Field(default=None, gt=0)
    final_retention_days: int | None = Field(default=None, gt=0)


def retention(store, sid, epoch):
    from .models import EpochRetention

    with store._transaction(immediate=False) as session:
        row = session.get(EpochRetention, (sid, epoch))
        return row.model_dump() if row else None


def checkpoint_deadline(store, sid, epoch):
    retention = store.retention(sid, epoch)
    if not retention or not retention["anchor"]:
        return None
    days = orjson.loads(retention["policy"]).get("checkpoint_retention_days")
    return (
        datetime.fromisoformat(retention["anchor"]) + timedelta(days=days)
        if days is not None
        else None
    )


def _deadline(store, session, row):
    from .models import (
        BODY_TABLES as _BODY_TABLES,
    )
    from .models import (
        TERMINAL_STATUSES as _TERMINAL,
    )
    from .models import (
        EpochRetention,
        SessionEntry,
        SessionHeader,
    )

    if row.category is None:
        return None
    header = session.get(SessionHeader, row.session_id)
    policy = orjson.loads(header.policy)
    if "retention_days" in policy:
        # Existing archives keep the old deadline; never map it onto new policy fields.
        days = policy["retention_days"]
        states = session.exec(
            select(SessionEntry)
            .where(SessionEntry.session_id == row.session_id)
            .order_by(SessionEntry.version)
        ).all()
        states = [
            entry
            for entry in states
            if entry.scope in {"parent", "phase"} and "status" in orjson.loads(entry.summary)
        ]
        anchor = (
            states[-1].created_at
            if states and orjson.loads(states[-1].summary)["status"] in _TERMINAL
            else None
        )
    else:
        if row.category not in _BODY_TABLES:
            return None
        epoch = orjson.loads(row.summary).get("execution_epoch")
        retained = session.get(EpochRetention, (row.session_id, epoch)) if epoch else None
        anchor = retained.anchor if retained else None
        days = (
            orjson.loads(retained.policy).get(f"{row.category}_retention_days")
            if retained
            else None
        )
    return (
        datetime.fromisoformat(anchor) + timedelta(days=days)
        if anchor and days is not None
        else None
    )


def expire(store, now=None, *, active=(), session_id=None):
    from .models import BODY_TABLES as _BODY_TABLES
    from .models import SessionEntry

    now = now or datetime.now(UTC)
    changed = 0
    with store._transaction() as session:
        statement = select(SessionEntry).where(
            SessionEntry.availability == "available", SessionEntry.category.is_not(None)
        )
        if session_id is not None:
            statement = statement.where(SessionEntry.session_id == session_id)
        expired = {}
        for row in session.exec(statement).all():
            if row.session_id in active:
                continue
            deadline = store._deadline(session, row)
            if deadline is None or now < deadline:
                continue
            if row.category in _BODY_TABLES:
                body = session.get(_BODY_TABLES[row.category], (row.session_id, row.version))
                if body:
                    session.delete(body)
            row.body, row.availability = None, "expired"
            session.add(row)
            expired.setdefault(row.session_id, []).append(row.version)
            changed += 1
        session.flush()
        for sid, versions in expired.items():
            store.write(
                sid,
                "expired:" + ",".join(map(str, versions)),
                stage=None,
                scope="availability",
                summary={"expired_versions": versions},
            )
        store._prune_prompts(session)
    return changed
