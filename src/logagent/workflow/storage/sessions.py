"""独立于 LangGraph checkpoint 的只读业务视图，供 API 和历史采集共用。"""

from __future__ import annotations

import asyncio
from datetime import datetime

from logagent.errors import LogAgentError
from logagent.models import ArtifactInfo, SessionRecord, SessionStatus
from logagent.workflow.storage.progress import active_phases, project_progress
from logagent.workflow.storage.reports import _availability, _bodies, _project_errors, read_phase


class SessionView:
    """从业务条目计算 session 摘要及阶段正文，不提供运行调度或写入接口。"""

    def __init__(self, store):
        """绑定业务存储，由调用方负责其生命周期。"""
        self._store = store

    async def mcp_binding(self, session_id):
        from logagent.models import WorkflowSnapshot
        entry = await asyncio.to_thread(self._store.entry, session_id, "snapshot")
        if not entry or entry["availability"] != "available" or not entry["body"]:
            return {"error": "Workflow 配置快照未保存或不可用；无法恢复 MCP 范围"}
        try:
            snapshot = WorkflowSnapshot.model_validate(entry["body"]["snapshot"])
        except ValueError:
            return {"error": "原 Workflow 使用旧版来源配置，MCP 绑定不可恢复"}
        return {
            "servers": {key: value.model_dump(mode="json") for key, value in snapshot.mcp_servers.items()},
            "sources": [{"source": source.id, "server": source.call.server, "tool": source.call.tool}
                        for source in snapshot.sources.values() if source.call.kind == "mcp"],
        }

    @staticmethod
    def _record(header: dict, entries: list[dict]) -> SessionRecord:
        """按业务版本顺序合并状态摘要与各阶段可用性。

        只有 parent/phase 作用域推进 session 状态；子项不会覆盖父级状态。
        终态事件设置结束时间，后续 running 事件清除结束时间。
        """
        entries = _project_errors(entries)
        state = {"status": "created", "stage": None, "error": None}
        workflow_name = None
        snapshot = "pending"
        finished_at = None
        for entry in entries:
            summary = entry["summary"]
            if entry["write_key"] == "created":
                workflow_name = summary.get("workflow_name")
            if entry["scope"] in {"parent", "phase"}:
                for key in ("status", "error"):
                    if key in summary:
                        state[key] = summary[key]
                if entry["scope"] == "phase" and isinstance(entry["body"], dict):
                    errors = entry["body"].get("errors", [])
                    if errors:
                        state["error"] = errors[-1]
                if entry["stage"] is not None:
                    state["stage"] = entry["stage"]
                if summary.get("status") in {
                    "completed",
                    "partial",
                    "failed",
                    "cancelled",
                    "interrupted",
                }:
                    finished_at = entry["created_at"]
                elif summary.get("status") == "running":
                    finished_at = None
            if entry["write_key"] == "snapshot":
                snapshot = entry["availability"]
        phases = active_phases(entries)
        artifacts = []
        for stage, entry in phases.items():
            related = _bodies(entries, entry) or ([entry] if entry["category"] else [])
            availability = (
                _availability(related)
                if stage in {"collect", "analyze", "aggregate"}
                else entry["availability"]
            )
            artifacts.append(
                ArtifactInfo(
                    stage=stage,
                    availability=availability,
                    content_version=max([entry["version"], *(item["version"] for item in related)])
                    if availability == "available"
                    else None,
                )
            )
        epoch, progress = project_progress(header["session_id"], entries)
        failures = [
            entry
            for entry in entries
            if entry["availability"] == "write_failed"
            and entry["scope"] != "archive_error"
            and entry["summary"].get("execution_epoch") == epoch
        ]
        if failures:
            state["error"] = failures[-1]["summary"].get("error")
            if state["status"] == "completed":
                state["status"] = "partial"
        return SessionRecord(
            session_id=header["session_id"],
            workflow_id=header["workflow_id"],
            workflow_name=workflow_name,
            version=entries[-1]["version"],
            created_at=header["created_at"],
            updated_at=entries[-1]["created_at"],
            finished_at=finished_at,
            snapshot_availability=snapshot,
            artifacts=artifacts,
            execution_epoch=epoch,
            progress=progress,
            **state,
        )

    async def get_session(self, session_id: str, *, version: int | None = None) -> SessionRecord:
        """在线程中读取最新或指定版本的条目，返回该版本的 session 摘要。"""
        header, entries = await asyncio.to_thread(
            self._store.entries, session_id, version, include_body=False
        )
        return self._record(header, entries)

    async def list_sessions(
        self,
        workflow_id: str | None = None,
        *,
        workflow_name: str | None = None,
        session_id: str | None = None,
        status: SessionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
        after: datetime | None = None,
        before: datetime | None = None,
        exclude_session_id: str | None = None,
    ) -> list[SessionRecord]:
        """校验分页与带时区的时间边界，筛选 session 后分页返回。

        名称按不区分大小写的子串匹配，ID 与状态精确匹配。
        时间筛选基于创建时间且包含端点；可排除当前 session，供历史采集使用。
        每条记录独立读取，不提供跨 session 的全局事务快照。
        """
        if (
            type(limit) is not int
            or not 1 <= limit <= 1000
            or type(offset) is not int
            or offset < 0
        ):
            raise LogAgentError("invalid_argument", "分页参数无效")
        if any(value is not None and value.tzinfo is None for value in (after, before)):
            raise LogAgentError("invalid_argument", "时间边界需要时区")
        if after is not None and before is not None and after > before:
            raise LogAgentError("invalid_argument", "时间区间无效")
        name_query = workflow_name.casefold() if workflow_name is not None else None
        records = []
        for sid in await asyncio.to_thread(self._store.session_ids):
            if sid == exclude_session_id:
                continue
            if session_id is not None and sid != session_id:
                continue
            record = await self.get_session(sid)
            if workflow_id is not None and record.workflow_id != workflow_id:
                continue
            if name_query is not None and (
                record.workflow_name is None or name_query not in record.workflow_name.casefold()
            ):
                continue
            if status is not None and record.status != status:
                continue
            if after is not None and record.created_at < after:
                continue
            if before is not None and record.created_at > before:
                continue
            records.append(record)
        return records[offset : offset + limit]

    async def get_phase_content(self, session_id, stage, *, version):
        return await read_phase(self._store, session_id, stage, version=version)
