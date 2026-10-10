"""业务报告只从归档读取，不决定图的执行状态。"""

import asyncio

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import ErrorInfo, Notification, PhaseContent, WorkflowStage

from .models import WorkflowResult
from .progress import active_phases


async def assemble_result(view, sid, snapshot, state):
    record = await view.get_session(sid)
    result = WorkflowResult(
        session_id=sid,
        workflow_id=snapshot.workflow.id,
        stage=state.get("phase", {}).get("stage", "collect"),
        status=state.get("status", "running"),
        stopped=state.get("stopped", False),
    )
    for stage in ("collect", "analyze", "aggregate", "notify", "finish"):
        content = await view.get_phase_content(sid, stage, version=record.version)
        if content.content:
            body = content.content
            for key in ("collection", "shared_input", "input_views", "analyses", "aggregate", "outputs", "deliveries"):
                if key in body:
                    result = WorkflowResult.model_validate(
                        {**result.model_dump(mode="json"), key: body[key]}
                    )
    if state.get("error"):
        result.errors = [ErrorInfo.model_validate(state["error"])]
    if record.error and record.error.code == "backup_failed":
        result.errors.append(record.error)
        if result.status == "completed":
            result.status = "partial"
    result.notifications = [
        Notification(
            session_id=sid,
            output_id=oid,
            title=snapshot.workflow.name or snapshot.workflow.id,
            text=text,
        )
        for oid, text in result.outputs.items()
    ]
    return result


async def read_phase(
    store,
    session_id: str,
    stage: WorkflowStage,
    *,
    version: int,
) -> PhaseContent:
    """读取指定业务版本之前最近一次该阶段正文及可用性。

    无阶段条目时返回 pending；未保存或过期正文返回对应可用性和空内容，
    非法阶段或不存在的业务版本由查询边界明确报错。
    """
    if stage not in {"collect", "analyze", "aggregate", "notify", "finish"}:
        raise WorkFLowWeaveError("invalid_argument", "阶段无效")
    _, entries = await asyncio.to_thread(store.entries, session_id, version)
    entries = _project_errors(entries)
    selected = active_phases(entries).get(stage)
    related = _bodies(entries, selected) if selected else []
    legacy = selected is not None and selected["category"] is not None
    if legacy:
        related = [selected]
    availability = (
        _availability(related)
        if selected and stage in {"collect", "analyze", "aggregate"}
        else selected["availability"]
        if selected
        else "pending"
    )
    content = None
    if availability == "available":
        content = dict(selected["body"] or {})
        bodies = [entry["body"] for entry in related if entry["availability"] == "available"]
        if legacy:
            pass
        elif stage == "collect":
            content["collection"] = bodies
        elif stage == "analyze":
            content["analyses"] = bodies
        elif stage == "aggregate":
            content["outputs"] = {
                entry["summary"]["output_id"]: entry["body"]["text"]
                for entry in related
                if entry["availability"] == "available"
            }
            metadata = content.pop("aggregate_meta", None)
            content["aggregate"] = (
                {**metadata, "text": content["outputs"].get("final", "")} if metadata else None
            )
        elif stage == "notify":
            content["deliveries"] = bodies
    return PhaseContent(
        session_id=session_id,
        version=version,
        stage=stage,
        content_version=max([selected["version"], *(item["version"] for item in related)])
        if selected and availability == "available"
        else None,
        availability=availability,
        content=content,
    )


def _project_errors(entries):
    """Unresolved archive errors occupy the missing result's projection only."""
    keys = {entry["write_key"] for entry in entries}
    return [
        (
            {
                **entry,
                "scope": entry["summary"]["result_scope"],
                "category": entry["summary"]["result_category"],
                "write_key": entry["summary"]["result_key"],
            }
            if entry["scope"] == "archive_error" and entry["summary"]["result_key"] not in keys
            else entry
        )
        for entry in entries
    ]


def _bodies(entries, phase):
    stage = phase["stage"]
    epoch = phase["summary"].get("execution_epoch")
    scope = {
        "collect": "collect",
        "analyze": "analyze",
        "aggregate": "output",
        "notify": "notification",
    }.get(stage)
    selected = [
        entry
        for entry in entries
        if entry["scope"] == scope
        and entry["summary"].get("execution_epoch") == epoch
        and (stage != "notify" or entry["write_key"].startswith("delivery:"))
    ]
    layout = next(
        (e["summary"].get("layout", []) for e in entries if e["write_key"] == "snapshot"), []
    )
    order = {
        (i.get("stage"), i.get("item_id"), i.get("output_id"), i.get("channel_id")): n
        for n, i in enumerate(layout)
    }
    return sorted(
        selected,
        key=lambda e: order.get(
            (
                stage,
                e["summary"].get("item_id"),
                e["summary"].get("output_id"),
                e["summary"].get("channel_id"),
            ),
            0,
        ),
    )


def _availability(entries):
    for status in ("expired", "write_failed", "not_saved"):
        if any(entry["availability"] == status for entry in entries):
            return status
    if any(entry["availability"] == "available" for entry in entries):
        return "available"
    if any(entry["availability"] == "pending" for entry in entries):
        return "pending"
    return "available"
