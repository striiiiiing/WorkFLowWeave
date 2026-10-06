"""Session fact projection and durable Sessions JSON materialization."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workflowweave.agent.contracts import SessionView
from workflowweave.agent.storage.events import EventLog
from workflowweave.errors import WorkFLowWeaveError


class SessionStore:
    def __init__(self, runtime: Path, workspace, bindings, invocations):
        self.runtime = runtime
        self.workspace = workspace
        self.bindings = bindings
        self.invocations = invocations
        self.views: dict[str, SessionView] = {}
        self._logs: dict[str, EventLog] = {}
        self._requests: dict[str, dict[str, tuple[str, str]]] = {}

    async def new_log(self, session_id: str) -> EventLog:
        log = EventLog(self.runtime, session_id)
        await log.initialize()
        return log

    def get(self, session_id: str) -> SessionView:
        session = self.views.get(session_id)
        if session is None:
            raise WorkFLowWeaveError("session_not_found", "Agent session 不存在")
        return session

    def log(self, session_id: str) -> EventLog:
        return self._logs[session_id]

    def requests(self, session_id: str) -> dict[str, tuple[str, str]]:
        return self._requests.setdefault(session_id, {})

    def add(self, session: SessionView, log: EventLog) -> None:
        self.views[session.session_id] = session
        self._logs[session.session_id] = log

    async def restore(self) -> None:
        history = self.runtime / "History"
        if not history.exists():
            return
        for directory in sorted(history.iterdir()):
            if not directory.is_dir() or not (directory / "events.jsonl").exists():
                continue
            log = EventLog(self.runtime, directory.name)
            await log.initialize()
            created = next((event for event in log.events if event["type"] == "session.created"), None)
            if created is None:
                continue
            workflow = next((event for event in log.events if event["type"] == "workflow.input"), None)
            terminal = next((event for event in reversed(log.events)
                             if event["type"] in {"turn.started", "turn.completed", "turn.failed",
                                                  "turn.cancelled", "turn.interrupted"}), None)
            status = "interrupted" if terminal and terminal["type"] in {
                "turn.started", "turn.interrupted"
            } else "created"
            if terminal is not None and terminal["type"] == "turn.started":
                # A process may die after turn.started and before its terminal
                # fact.  Make that boundary durable before exposing the session
                # to a new request; the old graph is never resumed.
                await log.append("turn.interrupted", turn_id=terminal.get("turn_id"),
                                 reason="process_restart")
            if terminal is not None and terminal["type"] == "turn.completed":
                status = "completed"
            elif terminal is not None and terminal["type"] == "turn.cancelled":
                status = "cancelled"
            elif terminal is not None and terminal["type"] == "turn.failed":
                status = "failed"
            turn_id = terminal.get("turn_id") if terminal else None
            await log.recover_interrupted()
            now = created["created_at"]
            session = SessionView(
                directory.name, created["branch_id"],
                created.get("model"), created.get("workflow_session_id"),
                workflow.get("input") if workflow else None, now, log.events[-1]["created_at"],
                status=status, turn_id=turn_id,
                parent_session_id=created.get("parent_session_id"),
                parent_turn_id=created.get("parent_turn_id"),
                parent_branch_id=created.get("parent_branch_id"),
                parent_event_id=created.get("parent_event_id"),
                workflow_task_id=created.get("workflow_task_id"),
                ai_config=self.invocations.read(directory.name) if created.get("has_ai_config") else None,
                system_prompt=created.get("system_prompt", ""),
                input_prompt=created.get("input_prompt", "{input}"),
                user_prompt=created.get("user_prompt", ""), tool_names=created.get("tool_names"),
            )
            self.add(session, log)
            started_turns = {
                event.get("turn_id") for event in log.events
                if event["type"] == "turn.started"
            }
            finished_turns = {
                event.get("turn_id") for event in log.events
                if event["type"] in {
                    "turn.completed", "turn.failed", "turn.cancelled", "turn.interrupted",
                }
            }
            for event in log.events:
                if event["type"] != "command.queued" or event.get("command") != "append":
                    continue
                queued_turn = event.get("queued_turn_id")
                text = event.get("text")
                request_id = event.get("request_id")
                digest = event.get("text_digest")
                if (isinstance(queued_turn, str) and isinstance(text, str)
                        and isinstance(request_id, str) and isinstance(digest, str)
                        and queued_turn not in started_turns
                        and queued_turn not in finished_turns):
                    self.requests(session.session_id)[request_id] = (queued_turn, digest)
            for event in log.events:
                if event["type"] in {"request.accepted", "command.queued"} and event.get("request_id"):
                    request_id = event.get("request_id")
                    digest = event.get("text_digest")
                    accepted_turn = event.get("turn_id")
                    if isinstance(request_id, str) and isinstance(digest, str) \
                            and isinstance(accepted_turn, str):
                        self.requests(session.session_id)[request_id] = (accepted_turn, digest)
            changed_model = next((event.get("model") for event in reversed(log.events)
                                  if event["type"] == "session.model.changed"), session.model)
            session.model = changed_model
            if any(event["type"] == "session.model.changed" for event in log.events):
                session.ai_config = None
            session.title = next((event.get("title", "") for event in reversed(log.events)
                                  if event["type"] == "session.title.changed"), "")
            self.views[directory.name] = session
            await self.persist(session)

    def document(self, session: SessionView) -> dict[str, Any]:
        budget = next((event["data"] for event in reversed(self.log(session.session_id).events)
                       if event["type"] == "context.budget"), None)
        resources = next((event["data"] for event in reversed(self.log(session.session_id).events)
                          if event["type"] == "turn.resources"), None)
        checkpoint_error = next((event.get("error") for event in reversed(self.log(session.session_id).events)
            if event["type"] == "turn.failed" and event.get("error", {}).get("code")
            in {"checkpoint_missing", "checkpoint_corrupt"}), None)
        return {"session_id": session.session_id, "branch_id": session.branch_id,
                "title": session.title,
                "session_kind": session.session_kind,
                "workflow_task_id": session.workflow_task_id,
                "model": session.model, "workflow_session_id": session.workflow_session_id,
                "parent_session_id": session.parent_session_id,
                "parent_turn_id": session.parent_turn_id,
                "parent_branch_id": session.parent_branch_id,
                "parent_event_id": session.parent_event_id,
                "created_at": session.created_at, "updated_at": session.updated_at,
                "status": session.status, "turn_id": session.turn_id,
                "context_budget": budget,
                "active_resources": resources,
                "history_path": f"Runtime/History/{session.session_id}/events.jsonl",
                "continuable": checkpoint_error is None,
                "continuation_error": checkpoint_error,
                "last_checkpoint_at": next((event["at"] for event in reversed(self.log(session.session_id).events)
                    if event.get("checkpoint_id")), None)}

    async def persist(self, session):
        await self.workspace.save_runtime(
            f"Sessions/{session.session_id}.json",
            json.dumps(self.document(session), ensure_ascii=False, indent=2).encode(),
        )
