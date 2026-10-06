"""Session use cases coordinated with the one turn admission boundary."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from workflowweave.agent.contracts import SessionView
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import AIConfig


def _new_id(prefix=""):
    return (prefix + uuid4().hex)[:80]

class SessionManager:
    def __init__(self, repository, turns, checkpoints, bindings, *, default_model=None,
                 resources=None, mcp_binding_reader=None, resolve_model=None,
                 initialize=None):
        self.repository = repository
        self.turns = turns
        self.checkpoints = checkpoints
        self.bindings = bindings
        self.default_model = default_model
        self.resources = resources
        self.mcp_binding_reader = mcp_binding_reader
        self.resolve_model = resolve_model
        self.initialize = initialize

    @property
    def sessions(self):
        return self.repository.views

    @property
    def runtime(self):
        return self.repository.runtime

    async def create_session(self, *, model: str | None = None,
                             workflow_session_id: str | None = None,
                             workflow_result: Any = None,
                             workflow_task_id: str | None = None,
                             ai_config: AIConfig | None = None,
                             system_prompt: str | None = None,
                             input_prompt: str | None = None,
                             user_prompt: str = "",
                             tool_names: list[str] | None = None,
                             session_id: str | None = None,
                             operation_id: str | None = None,
                             parent_session_id: str | None = None,
                             parent_turn_id: str | None = None,
                             parent_branch_id: str | None = None,
                             parent_event_id: int | None = None,
                             initial_messages: list | None = None,
                             mcp_binding: dict | None = None) -> dict[str, Any]:
        async with self.turns.admission_lock:
            if not self.turns.accepting:
                raise WorkFLowWeaveError("agent_busy", "Agent 当前暂停接收新会话")
            await self.initialize()
            if workflow_task_id is not None and workflow_session_id is None:
                raise WorkFLowWeaveError("invalid_argument", "task_id 需要 workflow_session_id")
            system_prompt = system_prompt if system_prompt is not None else (
                ai_config.system_prompt if ai_config is not None else ""
            )
            input_prompt = "{input}" if input_prompt is None else input_prompt
            sid = session_id or ("agent_" + hashlib.sha256(operation_id.encode()).hexdigest()[:32]
                                 if operation_id is not None else _new_id("agent_"))
            if sid in self.sessions:
                created = next((event for event in self.repository.log(sid).events
                                if event["type"] == "session.created"), None)
                if operation_id is not None and created is not None \
                        and created.get("operation_id") == operation_id:
                    return self.repository.document(self.sessions[sid])
                raise WorkFLowWeaveError("session_conflict", "Agent session 已存在")
            if mcp_binding is None:
                if workflow_session_id is not None:
                    mcp_binding = (await self.mcp_binding_reader(workflow_session_id)
                                   if self.mcp_binding_reader else
                                   {"error": "原 Workflow 的 MCP 绑定读取能力不可用"})
                else:
                    servers = self.resources.invocation_snapshot().get("mcp_servers", {}) if self.resources else {}
                    mcp_binding = {"servers": {key: value.model_dump(mode="json")
                                               for key, value in servers.items() if value.enabled},
                                   "sources": []}
            self.bindings.write(sid, mcp_binding)
            now = datetime.now(UTC).isoformat()
            session = SessionView(
                sid, _new_id("branch_"), model or self.default_model,
                workflow_session_id, workflow_result, now, now,
                parent_session_id=parent_session_id,
                parent_turn_id=parent_turn_id,
                parent_branch_id=parent_branch_id, parent_event_id=parent_event_id,
                workflow_task_id=workflow_task_id, ai_config=deepcopy(ai_config),
                system_prompt=system_prompt, input_prompt=input_prompt,
                user_prompt=user_prompt, tool_names=deepcopy(tool_names),
            )
            if ai_config is not None:
                self.repository.invocations.write(sid, ai_config)
            log = await self.repository.new_log(sid)
            if initial_messages is not None:
                await self.checkpoints.projection.aupdate_state(
                    {"configurable": {"thread_id": sid}}, {"messages": initial_messages}, as_node="projection",
                )
            created = await log.append(
                "session.created", branch_id=session.branch_id,
                operation_id=operation_id,
                model=session.model, workflow_session_id=workflow_session_id,
                workflow_task_id=workflow_task_id, session_kind=session.session_kind,
                has_ai_config=ai_config is not None, system_prompt=system_prompt,
                input_prompt=input_prompt, user_prompt=user_prompt, tool_names=tool_names,
                parent_session_id=parent_session_id, parent_turn_id=parent_turn_id,
                parent_branch_id=parent_branch_id, parent_event_id=parent_event_id,
            )
            if workflow_result is not None:
                await log.append("workflow.input", workflow_session_id=workflow_session_id,
                                         input=workflow_result)
                if initial_messages is not None:
                    await log.append("workflow.input.used", inherited=True)
            session.created_at = created["created_at"]
            session.updated_at = log.events[-1]["created_at"]
            self.repository.add(session, log)
            await self.repository.persist(session)
            return self.repository.document(session)

    async def fork(self, session_id: str, *, turn_id: str | None = None,
                   model: str | None = None, message_id: str | None = None,
                   child_session_id: str | None = None,
                   operation_id: str | None = None) -> dict[str, Any]:
        if child_session_id in self.sessions and operation_id is not None:
            created = next((event for event in self.repository.log(child_session_id).events
                            if event["type"] == "session.created"), None)
            if created is not None and created.get("operation_id") == operation_id:
                return self.repository.document(self.sessions[child_session_id])
        source = self.repository.get(session_id)
        async with self.turns.lock(source.session_id):
            if self.turns.active(source.session_id):
                raise WorkFLowWeaveError("session_busy", "运行中的 session 不能创建分支")
            user = None
            if message_id is not None:
                user = next((event for event in self.repository.log(source.session_id).events
                             if event["type"] == "message.user" and event.get("message_id") == message_id), None)
                if user is None:
                    raise WorkFLowWeaveError("message_not_found", "只能从用户消息创建编辑分支")
            selected_turn = user["turn_id"] if user else turn_id or source.turn_id
            terminal = next((event for event in self.repository.log(source.session_id).events
                             if event.get("turn_id") == selected_turn and event["type"] == "turn.completed"), None)
            if terminal is None:
                raise WorkFLowWeaveError("turn_not_found", "分支起点必须是已完成轮次")
            checkpoint_id = terminal.get("checkpoint_id")
            if not checkpoint_id:
                raise WorkFLowWeaveError("checkpoint_missing", "该历史节点缺少精确 checkpoint，不能猜测分支边界")
            graph = self.checkpoints.projection
            state = await graph.aget_state({"configurable": {
                "thread_id": session_id, "checkpoint_id": checkpoint_id,
            }})
            messages = deepcopy(state.values.get("messages", []))
            if not messages:
                raise WorkFLowWeaveError("checkpoint_missing", "分支起点 checkpoint 缺失")
            if user is not None:
                index = next((i for i, message in enumerate(messages) if message.id == message_id), None)
                if index is None:
                    # The end checkpoint may already summarize the edited node.
                    # Read its original input checkpoint through the public history API.
                    async for snapshot in graph.aget_state_history({"configurable": {"thread_id": session_id}}):
                        candidate = snapshot.values.get("messages", [])
                        index = next((i for i, message in enumerate(candidate) if message.id == message_id), None)
                        if index is not None:
                            messages = deepcopy(candidate)
                            break
                if index is None:
                    raise WorkFLowWeaveError("checkpoint_missing", "用户消息的原始 checkpoint 不可用")
                messages = messages[:index]
        child = await self.create_session(
            model=model or source.model,
            session_id=child_session_id, operation_id=operation_id,
            workflow_session_id=source.workflow_session_id,
            workflow_result=source.workflow_input, mcp_binding=deepcopy(self.bindings.read(source.session_id)),
            workflow_task_id=source.workflow_task_id,
            ai_config=source.ai_config if model is None else None,
            system_prompt=source.system_prompt, input_prompt=source.input_prompt,
            user_prompt=source.user_prompt, tool_names=source.tool_names,
            parent_session_id=source.session_id, parent_turn_id=selected_turn,
            parent_branch_id=source.branch_id,
            parent_event_id=user["id"] - 1 if user else terminal["id"],
            initial_messages=messages,
        )
        await self.repository.log(child["session_id"]).append(
            "branch.created", parent_session_id=session_id, parent_turn_id=selected_turn,
            parent_branch_id=source.branch_id, source_checkpoint_id=checkpoint_id,
            edited_message_id=message_id,
        )
        return child

    async def history(self, session_id: str) -> list[dict[str, Any]]:
        session = self.repository.get(session_id)
        inherited = []
        if session.parent_session_id is not None:
            parent = await self.history(session.parent_session_id)
            inherited = [event for event in parent
                         if event["session_id"] != session.parent_session_id
                         or event["id"] <= (session.parent_event_id or 0)]
        return [*inherited, *await self.repository.log(session.session_id).replay()]

    async def set_model(self, session_id: str, model: str):
        session = self.repository.get(session_id)
        if self.resources is not None and self.resolve_model is not None:
            self.resolve_model(model, self.resources.invocation_snapshot())
        async with self.turns.lock(session.session_id):
            event = await self.repository.log(session.session_id).append("session.model.changed", model=model)
            session.model, session.updated_at = model, event["at"]
            session.ai_config = None
            await self.repository.persist(session)
        return self.repository.document(session)

    async def set_title(self, session_id: str, title: str):
        cleaned = title.strip()
        if not cleaned or len(cleaned) > 120:
            raise WorkFLowWeaveError("invalid_argument", "话题名称必须为 1 到 120 个字符")
        session = self.repository.get(session_id)
        async with self.turns.lock(session.session_id):
            event = await self.repository.log(session.session_id).append("session.title.changed", title=cleaned)
            session.title, session.updated_at = cleaned, event["at"]
            await self.repository.persist(session)
        return self.repository.document(session)

    def model_views(self):
        if self.resources is None:
            return []
        return [{"reference": f"{ai.id}:{name}", "provider": ai.provider,
                 "ai": ai.id, "model": name}
                for ai in self.resources.list("ai") for name in ai.models]

    async def source(self, session_id: str):
        session = self.repository.get(session_id)
        if session.parent_session_id:
            return await self.source(session.parent_session_id)
        return {"workflow_session_id": session.workflow_session_id,
                "workflow_task_id": session.workflow_task_id,
                "input": session.workflow_input, "created_at": session.created_at}

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return self.repository.document(self.repository.get(session_id))

    async def list_sessions(self) -> list[dict[str, Any]]:
        return [self.repository.document(item) for item in self.sessions.values()]
