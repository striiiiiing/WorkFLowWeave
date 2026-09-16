"""The shared read-only view of business archives, independent of checkpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime

import orjson

from logagent.errors import LogAgentError
from logagent.models import ArtifactInfo, PhaseContent, SessionRecord, WorkflowStage


class SessionView:
    def __init__(self, store):
        self._store = store

    @staticmethod
    def _record(header: dict, entries: list[dict]) -> SessionRecord:
        state = {"status": "created", "stage": None, "error": None}
        phases = {}
        snapshot = "pending"
        finished_at = None
        for entry in entries:
            summary = entry["summary"]
            if entry["scope"] in {"parent", "phase"}:
                for key in ("status", "error"):
                    if key in summary:
                        state[key] = summary[key]
                if entry["stage"] is not None:
                    state["stage"] = entry["stage"]
                if summary.get("status") in {"completed", "partial", "failed", "cancelled", "interrupted"}:
                    finished_at = entry["created_at"]
                elif summary.get("status") == "running":
                    finished_at = None
            if entry["write_key"] == "snapshot":
                snapshot = entry["availability"]
            if entry["scope"] == "phase":
                phases[entry["stage"]] = ArtifactInfo(
                    stage=entry["stage"], availability=entry["availability"],
                    size_bytes=len(orjson.dumps(entry["body"])) if entry["body"] is not None else None,
                )
        return SessionRecord(
            session_id=header["session_id"], workflow_id=header["workflow_id"],
            version=entries[-1]["version"], created_at=header["created_at"],
            updated_at=entries[-1]["created_at"], finished_at=finished_at,
            snapshot_availability=snapshot, artifacts=list(phases.values()), **state,
        )

    async def get_session(self, session_id: str, *, version: int | None = None) -> SessionRecord:
        header, entries = await asyncio.to_thread(self._store.entries, session_id, version)
        return self._record(header, entries)

    async def list_sessions(
        self, workflow_id: str | None = None, *, limit: int = 100, offset: int = 0,
        after: datetime | None = None, before: datetime | None = None,
        exclude_session_id: str | None = None,
    ) -> list[SessionRecord]:
        if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
            raise LogAgentError("invalid_argument", "分页参数无效")
        if any(value is not None and value.tzinfo is None for value in (after, before)):
            raise LogAgentError("invalid_argument", "时间边界需要时区")
        if after is not None and before is not None and after > before:
            raise LogAgentError("invalid_argument", "时间区间无效")
        records = []
        for sid in await asyncio.to_thread(self._store.session_ids):
            if sid == exclude_session_id:
                continue
            record = await self.get_session(sid)
            if workflow_id is not None and record.workflow_id != workflow_id:
                continue
            if after is not None and record.created_at < after:
                continue
            if before is not None and record.created_at > before:
                continue
            records.append(record)
        return records[offset:offset + limit]

    async def get_phase_content(
        self, session_id: str, stage: WorkflowStage, *, version: int,
    ) -> PhaseContent:
        if stage not in {"collect", "analyze", "aggregate", "notify", "finish"}:
            raise LogAgentError("invalid_argument", "阶段无效")
        _, entries = await asyncio.to_thread(self._store.entries, session_id, version)
        selected = next(
            (e for e in reversed(entries) if e["scope"] == "phase" and e["stage"] == stage), None
        )
        return PhaseContent(
            session_id=session_id, version=version, stage=stage,
            availability=selected["availability"] if selected else "pending",
            content=selected["body"] if selected else None,
        )
