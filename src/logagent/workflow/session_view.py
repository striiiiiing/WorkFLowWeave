"""独立于 LangGraph checkpoint 的只读业务视图，供 API 和历史采集共用。"""

from __future__ import annotations

import asyncio
from datetime import datetime

import orjson

from logagent.errors import LogAgentError
from logagent.models import ArtifactInfo, PhaseContent, SessionRecord, WorkflowStage


class SessionView:
    """从业务条目计算 session 摘要及阶段正文，不提供运行调度或写入接口。"""
    def __init__(self, store):
        """绑定业务存储，由调用方负责其生命周期。"""
        self._store = store

    @staticmethod
    def _record(header: dict, entries: list[dict]) -> SessionRecord:
        """按业务版本顺序合并状态摘要与各阶段可用性。

        只有 parent/phase 作用域推进 session 状态；子项不会覆盖父级状态。
        终态事件设置结束时间，后续 running 事件清除结束时间。
        """
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
        """在线程中读取最新或指定版本的条目，返回该版本的 session 摘要。"""
        header, entries = await asyncio.to_thread(self._store.entries, session_id, version)
        return self._record(header, entries)

    async def list_sessions(
        self, workflow_id: str | None = None, *, limit: int = 100, offset: int = 0,
        after: datetime | None = None, before: datetime | None = None,
        exclude_session_id: str | None = None,
    ) -> list[SessionRecord]:
        """校验分页与带时区的时间边界，筛选 session 后分页返回。

        时间筛选基于创建时间且包含端点；可排除当前 session，供历史采集使用。
        每条记录独立读取，不提供跨 session 的全局事务快照。
        """
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
        """读取指定业务版本之前最近一次该阶段正文及可用性。

        无阶段条目时返回 pending；未保存或过期正文返回对应可用性和空内容，
        非法阶段或不存在的业务版本由查询边界明确报错。
        """
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
