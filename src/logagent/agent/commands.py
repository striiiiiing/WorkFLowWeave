"""Agent commands shared by the Web, QQ and test conversation transports."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from pydantic import Field

from logagent.errors import LogAgentError
from logagent.models import ID, StrictModel


class AgentCommand(StrictModel):
    channel: ID = "web"
    session: ID | None = None
    priority: Literal["stop", "command", "conversation"] | None = None
    request_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1)
    text: str = ""
    model: str | None = None
    action: Literal["message", "new", "resume", "stop", "append", "compact", "fork", "workflow"] | None = None
    workflow_session_id: ID | None = None
    workflow_id: ID | None = None
    workflow_result: object | None = None
    turn_id: ID | None = None
    message_id: ID | None = None

    def operation(self) -> tuple[str, str]:
        return parse_command(self.text) if self.action is None else (self.action, self.text)


def parse_command(text: str) -> tuple[str, str]:
    """Parse a legacy slash command or classify arbitrary text as a message."""
    head, _, argument = text.strip().partition(" ")
    actions = {
        "/new": "new",
        "/resume": "resume",
        "/stop": "stop",
        "/append": "append",
        "/compact": "compact",
        "/fork": "fork",
        "/workflow": "workflow",
    }
    if head.startswith("/") and head not in actions:
        raise LogAgentError("invalid_argument", "未知 Agent 命令")
    return actions.get(head, "message"), argument if head in actions else text


class AgentChannel:
    """Shared Agent command boundary for Web, QQ, and test transports."""

    def __init__(self, service, session_view=None):
        self.service = service
        self.session_view = session_view

    async def dispatch(self, envelope: AgentCommand, *,
                       valid: Callable[[], bool] | None = None) -> dict:
        action, argument = envelope.operation()

        priority = "stop" if action == "stop" else (
            "command" if action in {"new", "resume", "append", "compact", "fork", "workflow"} else "conversation"
        )
        if envelope.priority is not None and envelope.priority != priority:
            raise LogAgentError("invalid_argument", "priority 与命令类别不一致")

        result, kind = await self._execute(envelope, action, argument, valid=valid)
        return {
            "channel": envelope.channel,
            "session": envelope.session,
            "priority": priority,
            "kind": kind,
            "result": result,
        }

    async def events(self, session_id: str, *, after: int = 0) -> list[dict]:
        return await self.service.events(session_id, after=after)

    async def get_session(self, session_id: str) -> dict:
        return await self.service.get_session(session_id)

    async def wait(self, turn_id: str) -> dict:
        return await self.service.wait(turn_id)

    async def wait_command(self, session_id: str, *, request_id: str | None = None,
                           event_id: int | None = None) -> dict:
        cursor = event_id or 0
        while True:
            for event in await self.wait_events(session_id, after=cursor):
                cursor = max(cursor, event["id"])
                if event["type"] not in {"command.completed", "command.failed", "command.cancelled"}:
                    continue
                if request_id is not None and event.get("request_id") != request_id:
                    continue
                if event_id is not None and event.get("command_event_id") != event_id:
                    continue
                return event

    async def wait_events(self, session_id: str, *, after: int, wait_seconds: float = 0.5) -> list[dict]:
        return await self.service.wait_events(session_id, after=after, wait_seconds=wait_seconds)

    async def _execute(self, envelope: AgentCommand, action: str, argument: str, *,
                       valid: Callable[[], bool] | None = None):
        if action == "new":
            result = await self._create(envelope)
            return result, "session"
        if action == "resume":
            session_id = argument or envelope.session or None
            if session_id is None:
                raise LogAgentError("invalid_argument", "恢复会话需要 session")
            return await self.service.get_session(session_id), "session"
        if action == "workflow":
            if envelope.workflow_session_id or argument:
                workflow_session_id = envelope.workflow_session_id or argument
                result = await self._create(envelope, workflow_session_id=workflow_session_id)
                return result, "session"
            if envelope.workflow_id is not None:
                source = await self._latest_workflow_session(envelope.workflow_id)
                result = await self._create(envelope, workflow_session_id=source)
                return result, "session"
            if self.session_view is None:
                raise LogAgentError("not_ready", "Workflow 会话读取服务尚未装配")
            records = await self.session_view.list_sessions(limit=100)
            return [record.model_dump(mode="json") for record in records], "workflows"

        session_id = envelope.session
        if action == "message":
            if session_id is None:
                raise LogAgentError("invalid_argument", "消息需要 session")
            submit = getattr(self.service, "submit_after_idle", self.service.submit)
            if valid is None:
                result = await submit(session_id, envelope.text, request_id=envelope.request_id)
            else:
                result = await submit(
                    session_id, envelope.text, request_id=envelope.request_id, valid=valid,
                )
            return result, "turn"
        if action == "stop":
            return await self.service.cancel(self._require_session(session_id)), "session"
        if action == "append":
            return await self.service.append(
                self._require_session(session_id), argument, request_id=envelope.request_id,
            ), "turn"
        if action == "compact":
            return await self.service.compact(self._require_session(session_id)), "turn"
        if action == "fork":
            return await self.service.fork(
                self._require_session(session_id), turn_id=envelope.turn_id or argument or None,
                model=envelope.model, message_id=envelope.message_id,
                child_session_id=self._operation_session(envelope),
                operation_id=self._operation_id(envelope),
            ), "session"
        raise LogAgentError("invalid_argument", "未知 Agent 命令")

    async def _create(self, envelope: AgentCommand, *, workflow_session_id: str | None = None):
        workflow_session_id = workflow_session_id or envelope.workflow_session_id
        workflow_result = envelope.workflow_result
        if workflow_session_id is not None:
            if workflow_result is not None:
                raise LogAgentError("invalid_argument", "绑定 Workflow 时由服务读取原始结果，不接受覆盖")
            workflow_result = await self._workflow_result(workflow_session_id)
        return await self.service.create_session(
            model=envelope.model,
            workflow_session_id=workflow_session_id,
            workflow_result=workflow_result,
            session_id=self._operation_session(envelope),
            operation_id=self._operation_id(envelope),
        )

    @staticmethod
    def _operation_id(envelope: AgentCommand) -> str | None:
        return envelope.request_id if envelope.request_id.startswith("channel:") else None

    @classmethod
    def _operation_session(cls, envelope: AgentCommand) -> str | None:
        operation_id = cls._operation_id(envelope)
        return ("agent_" + hashlib.sha256(operation_id.encode()).hexdigest()[:32]
                if operation_id is not None else None)

    async def recover_request(self, operation_id: str, *, channel: str,
                              operation: str) -> tuple[dict, str] | None:
        for session in self.service.sessions.values():
            for event in session.log.events:
                if event["type"] == "session.created" and event.get("operation_id") == operation_id:
                    return ({"channel": channel, "kind": "session", "priority": "command",
                             "result": await self.service.get_session(session.session_id)}, "completed")
                if event["type"] == "request.accepted" and event.get("request_id") == operation_id:
                    terminal = next((fact for fact in reversed(session.log.events)
                                     if fact.get("turn_id") == event["turn_id"]
                                     and fact["type"] in {"turn.completed", "turn.failed",
                                                          "turn.cancelled", "turn.interrupted"}), None)
                    status = (terminal["type"].removeprefix("turn.")
                              if terminal is not None else "outcome_unknown")
                    return ({"channel": channel, "kind": "turn",
                             "priority": "conversation" if operation == "message" else "command",
                             "result": {"session_id": session.session_id,
                                        "turn_id": event["turn_id"], "deduplicated": True}}, status)
        return None

    async def recover_initial_session(self, operation_id: str) -> str | None:
        created_id = f"{operation_id}:new"
        for session in self.service.sessions.values():
            if any(event["type"] == "session.created" and
                   event.get("operation_id") == created_id for event in session.log.events):
                return session.session_id
        return None

    async def _workflow_result(self, session_id: str) -> dict:
        if self.session_view is None:
            raise LogAgentError("not_ready", "Workflow 会话读取服务尚未装配")
        record = await self.session_view.get_session(session_id)
        if record.status not in {"completed", "partial"}:
            raise LogAgentError("workflow_result_unavailable", "Workflow 运行尚无最终结果")
        phase = await self.session_view.get_phase_content(session_id, "aggregate", version=record.version)
        if phase.availability != "available" or phase.content is None:
            raise LogAgentError("workflow_result_unavailable", "Workflow 最终结果正文不可用")
        return {
            "outputs": phase.content.get("outputs", {}),
            "aggregate": phase.content.get("aggregate"),
            "workflow_id": record.workflow_id,
            "finished_at": (record.finished_at or record.updated_at).isoformat(),
        }

    async def _latest_workflow_session(self, workflow_id: str) -> str:
        if self.session_view is None:
            raise LogAgentError("not_ready", "Workflow 会话读取服务尚未装配")
        records = await self.session_view.list_sessions(workflow_id=workflow_id, limit=1000)
        finished = [record for record in records if record.status in {"completed", "partial"}]
        if not finished:
            raise LogAgentError("workflow_result_unavailable", "Workflow 没有可继续的结果")
        latest = max(finished, key=lambda record: record.finished_at or record.updated_at)
        return latest.session_id

    @staticmethod
    def _require_session(session_id: str | None) -> str:
        if session_id is None:
            raise LogAgentError("invalid_argument", "此命令需要 session")
        return session_id
