"""Long-lived Agent sessions backed by LangGraph and the event log."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import tempfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, MessagesState, StateGraph

from logagent.agent.artifacts import ArtifactStore
from logagent.agent.builtin import grep, plugin, read, shell, write
from logagent.agent.builtin.declaration import ToolDeclaration
from logagent.agent.config import AgentConfig
from logagent.agent.context import build_system_prompt
from logagent.agent.events import EventLog
from logagent.agent.gateway import InvocationSnapshot, PluginGateway
from logagent.agent.graph import AgentToolContext, create_graph
from logagent.agent.sandbox import ShellSandbox
from logagent.agent.scheduling import ToolScheduler
from logagent.agent.workspace import RuntimeIdentity, WorkspaceBackend
from logagent.errors import LogAgentError
from logagent.models import CollectionContext

ModelProvider = Callable[["AgentSession"], Any]
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentSession:
    session_id: str
    branch_id: str
    model: str | None
    workflow_session_id: str | None
    workflow_input: Any
    created_at: str
    updated_at: str
    status: str = "created"
    turn_id: str | None = None
    request_ids: dict[str, tuple[str, str]] = field(default_factory=dict)
    log: EventLog | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task | None = None
    compact_pending: bool = False
    compact_events: list[int] = field(default_factory=list)
    stop_requested: bool = False
    finishing: bool = False
    parent_session_id: str | None = None
    parent_turn_id: str | None = None
    parent_branch_id: str | None = None
    parent_event_id: int | None = None
    pending_appends: list[tuple[str, str, str, str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _TurnResources:
    """Resources captured before a turn and never changed during that turn."""

    config: AgentConfig
    ai_config: Any | None
    model: str | None
    summary_ai_config: Any | None
    summary_model: str | None
    tools_generation: int | None
    declarations: tuple[ToolDeclaration, ...]
    gateway: Any | None


def _new_id(prefix: str = "") -> str:
    value = prefix + uuid4().hex
    return value[:80]


@asynccontextmanager
async def _null_async_context(value=None):
    """Async context helper for injected providers without a second lease."""
    yield value


class AgentService:
    """Own all Agent session tasks while sharing one workspace scheduler."""

    def __init__(self, workspace: Path, runtime: Path, *, config: AgentConfig | None = None,
                 model_provider: ModelProvider | None = None, ai_service=None,
                 ai_config=None, model: str | None = None, checkpointer=None,
                 resources=None, plugins=None, collectors=None, channels=None,
                 declarations: list[ToolDeclaration] | None = None,
                 gateway_factory: Callable[[AgentSession], Any] | None = None,
                 collection_context_factory: Callable[[AgentSession], CollectionContext] | None = None,
                 read_only_tools: bool = False):
        self.config = (config or AgentConfig()).model_copy(deep=True)
        self.workspace = WorkspaceBackend(workspace, runtime)
        self.runtime = Path(runtime).absolute()
        self.config_path = self.runtime.parent / "config.json"
        self.scheduler = ToolScheduler(self.config.read_concurrency)
        self.artifacts = ArtifactStore(self.workspace)
        self.model_provider = model_provider
        self.ai_service = ai_service
        self.ai_config = ai_config
        self.default_model = model
        self.resources = resources
        self.plugins = plugins
        self.collectors = collectors
        self.channels = channels
        self.checkpointer = checkpointer
        self._checkpointer_context = None
        self._owns_checkpointer = checkpointer is None
        self.gateway_factory = gateway_factory
        self.collection_context_factory = collection_context_factory
        self._declarations = declarations or [plugin.plugin, read.plugin, write.plugin,
                                               grep.plugin, shell.plugin]
        if read_only_tools:
            self._declarations = [item for item in self._declarations if item.execution == "read"]
        self.sessions: dict[str, AgentSession] = {}
        self._turns: dict[str, asyncio.Task] = {}
        self._admissions: set[asyncio.Task] = set()
        self._initialized = False
        self._accepting = True
        self._admission_lock = asyncio.Lock()

    @property
    def accepting(self) -> bool:
        return self._accepting

    async def pause_admission(self) -> int:
        """Stop new turns and return the number of currently active turns."""
        async with self._admission_lock:
            self._accepting = False
            return sum(1 for task in self._turns.values() if not task.done())

    def resume_admission(self) -> None:
        self._accepting = True

    async def initialize(self) -> None:
        if self._initialized:
            return
        if self.config_path.exists():
            self.config = AgentConfig.model_validate_json(self.config_path.read_text())
        await self.workspace.initialize()
        if not (self.workspace.root / "AGENTS.md").exists():
            await self.workspace.write("AGENTS.md", "overwrite", (
                "协助用户分析日志和 Workflow 结果。用 plugin 按需发现、读取 Schema 并单次调用 Collector。\n"
                "通过 read(\"Runtime/self.json\") 查看当前会话与来源。read/grep 用于查阅文件；"
                "在相应写能力可用且值得长期保存时，用 write 维护 Memory/YYYY-MM-DD.md 或 History/<session>.md。\n"
                "Shell 是单次执行；同组工具可并发，有前后依赖的调用分成两个模型步骤。"
                "工具结果未知时告知用户，不自动重做副作用。\n"
            ), expected_hash="*")
        if self.checkpointer is None:
            self._checkpointer_context = AsyncSqliteSaver.from_conn_string(
                str(self.runtime / "checkpoints.sqlite")
            )
            self.checkpointer = await self._checkpointer_context.__aenter__()
            await self.checkpointer.setup()
        await self._restore_sessions()
        self._initialized = True

    async def _restore_sessions(self) -> None:
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
                             if event["type"].startswith("turn.")), None)
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
            session = AgentSession(
                directory.name, created.get("branch_id", _new_id("branch_")),
                created.get("model"), created.get("workflow_session_id"),
                workflow.get("input") if workflow else None, now, log.events[-1]["created_at"],
                status=status, turn_id=turn_id, log=log,
                parent_session_id=created.get("parent_session_id"),
                parent_turn_id=created.get("parent_turn_id"),
                parent_branch_id=created.get("parent_branch_id"),
                parent_event_id=created.get("parent_event_id"),
            )
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
                    session.request_ids[request_id] = (queued_turn, digest)
            for event in log.events:
                if event["type"] in {"request.accepted", "command.queued"} and event.get("request_id"):
                    request_id = event.get("request_id")
                    digest = event.get("text_digest")
                    accepted_turn = event.get("turn_id")
                    if isinstance(request_id, str) and isinstance(digest, str) \
                            and isinstance(accepted_turn, str):
                        session.request_ids[request_id] = (accepted_turn, digest)
            changed_model = next((event.get("model") for event in reversed(log.events)
                                  if event["type"] == "session.model.changed"), session.model)
            session.model = changed_model
            self.sessions[directory.name] = session
            await self._persist_session(session)

    async def close(self) -> None:
        async with self._admission_lock:
            self._accepting = False
        if self._admissions:
            await asyncio.shield(asyncio.gather(*self._admissions, return_exceptions=True))
        tasks = [task for task in self._turns.values() if not task.done()]
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._turns.clear()
        if self._owns_checkpointer and self._checkpointer_context is not None:
            await self._checkpointer_context.__aexit__(None, None, None)
            self._checkpointer_context = None

    async def create_session(self, *, model: str | None = None,
                             workflow_session_id: str | None = None,
                             workflow_result: Any = None,
                             session_id: str | None = None,
                             parent_session_id: str | None = None,
                             parent_turn_id: str | None = None,
                             parent_branch_id: str | None = None,
                             parent_event_id: int | None = None,
                             initial_messages: list | None = None) -> dict[str, Any]:
        async with self._admission_lock:
            if not self._accepting:
                raise LogAgentError("agent_busy", "Agent 当前暂停接收新会话")
            await self.initialize()
            sid = session_id or _new_id("agent_")
            if sid in self.sessions:
                raise LogAgentError("session_conflict", "Agent session 已存在")
            now = datetime.now(UTC).isoformat()
            session = AgentSession(
                sid, _new_id("branch_"), model or self.default_model,
                workflow_session_id, workflow_result, now, now,
                log=EventLog(self.runtime, sid),
                parent_session_id=parent_session_id,
                parent_turn_id=parent_turn_id,
                parent_branch_id=parent_branch_id, parent_event_id=parent_event_id,
            )
            await session.log.initialize()
            if initial_messages is not None:
                await self._projection_graph().aupdate_state(
                    {"configurable": {"thread_id": sid}}, {"messages": initial_messages}, as_node="projection",
                )
            created = await session.log.append(
                "session.created", branch_id=session.branch_id,
                model=session.model, workflow_session_id=workflow_session_id,
                parent_session_id=parent_session_id, parent_turn_id=parent_turn_id,
                parent_branch_id=parent_branch_id, parent_event_id=parent_event_id,
            )
            if workflow_result is not None:
                await session.log.append("workflow.input", workflow_session_id=workflow_session_id,
                                         input=workflow_result)
            session.created_at = created["created_at"]
            session.updated_at = session.log.events[-1]["created_at"]
            self.sessions[sid] = session
            await self._persist_session(session)
            return self._session_view(session)

    def _projection_graph(self):
        """Public state API for copying a message projection, never pending tasks."""
        builder = StateGraph(MessagesState)
        builder.add_node("projection", lambda state: {})
        builder.set_entry_point("projection")
        builder.add_edge("projection", END)
        return builder.compile(checkpointer=self.checkpointer)

    async def fork(self, session_id: str, *, turn_id: str | None = None,
                   model: str | None = None, message_id: str | None = None) -> dict[str, Any]:
        source = self._session(session_id)
        async with source.lock:
            if source.task is not None and not source.task.done():
                raise LogAgentError("session_busy", "运行中的 session 不能创建分支")
            user = None
            if message_id is not None:
                user = next((event for event in source.log.events
                             if event["type"] == "message.user" and event.get("message_id") == message_id), None)
                if user is None:
                    raise LogAgentError("message_not_found", "只能从用户消息创建编辑分支")
            selected_turn = user["turn_id"] if user else turn_id or source.turn_id
            terminal = next((event for event in source.log.events
                             if event.get("turn_id") == selected_turn and event["type"] == "turn.completed"), None)
            if terminal is None:
                raise LogAgentError("turn_not_found", "分支起点必须是已完成轮次")
            checkpoint_id = terminal.get("checkpoint_id")
            if not checkpoint_id:
                raise LogAgentError("checkpoint_missing", "该历史节点缺少精确 checkpoint，不能猜测分支边界")
            graph = self._projection_graph()
            state = await graph.aget_state({"configurable": {
                "thread_id": session_id, "checkpoint_id": checkpoint_id,
            }})
            messages = deepcopy(state.values.get("messages", []))
            if not messages:
                raise LogAgentError("checkpoint_missing", "分支起点 checkpoint 缺失")
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
                    raise LogAgentError("checkpoint_missing", "用户消息的原始 checkpoint 不可用")
                messages = messages[:index]
        child = await self.create_session(
            model=model or source.model,
            workflow_session_id=source.workflow_session_id,
            parent_session_id=source.session_id, parent_turn_id=selected_turn,
            parent_branch_id=source.branch_id,
            parent_event_id=user["id"] - 1 if user else terminal["id"],
            initial_messages=messages,
        )
        await self.sessions[child["session_id"]].log.append(
            "branch.created", parent_session_id=session_id, parent_turn_id=selected_turn,
            parent_branch_id=source.branch_id, source_checkpoint_id=checkpoint_id,
            edited_message_id=message_id,
        )
        return child

    async def history(self, session_id: str) -> list[dict[str, Any]]:
        session = self._session(session_id)
        inherited = []
        if session.parent_session_id is not None:
            parent = await self.history(session.parent_session_id)
            inherited = [event for event in parent
                         if event["session_id"] != session.parent_session_id
                         or event["id"] <= (session.parent_event_id or 0)]
        return [*inherited, *await session.log.replay()]

    def _session_view(self, session: AgentSession) -> dict[str, Any]:
        budget = next((event["data"] for event in reversed(session.log.events)
                       if event["type"] == "context.budget"), None)
        resources = next((event["data"] for event in reversed(session.log.events)
                          if event["type"] == "turn.resources"), None)
        checkpoint_error = next((event.get("error") for event in reversed(session.log.events)
            if event["type"] == "turn.failed" and event.get("error", {}).get("code")
            in {"checkpoint_missing", "checkpoint_corrupt"}), None)
        return {"session_id": session.session_id, "branch_id": session.branch_id,
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
                "last_checkpoint_at": next((event["at"] for event in reversed(session.log.events)
                    if event.get("checkpoint_id")), None)}

    async def _persist_session(self, session):
        await self.workspace.save_runtime(
            f"Sessions/{session.session_id}.json",
            json.dumps(self._session_view(session), ensure_ascii=False, indent=2).encode(),
        )

    async def set_model(self, session_id: str, model: str):
        session = self._session(session_id)
        if self.resources is not None and self.model_provider is None:
            self._resolve_model(model, self.resources.invocation_snapshot())
        async with session.lock:
            event = await session.log.append("session.model.changed", model=model)
            session.model, session.updated_at = model, event["at"]
            await self._persist_session(session)
        return self._session_view(session)

    def model_views(self):
        if self.resources is None:
            return []
        return [{"reference": f"{ai.id}:{name}", "provider": ai.provider,
                 "ai": ai.id, "model": name}
                for ai in self.resources.list("ai") for name in ai.models]

    async def source(self, session_id: str):
        session = self._session(session_id)
        if session.parent_session_id:
            return await self.source(session.parent_session_id)
        return {"workflow_session_id": session.workflow_session_id,
                "input": session.workflow_input, "created_at": session.created_at}

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return self._session_view(self._session(session_id))

    async def list_sessions(self) -> list[dict[str, Any]]:
        return [self._session_view(item) for item in self.sessions.values()]

    def _session(self, session_id: str) -> AgentSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise LogAgentError("session_not_found", "Agent session 不存在")
        return session

    async def _start_turn_locked(self, session: AgentSession, text: str, *,
                                 request_id: str, turn_id: str | None = None,
                                 digest: str | None = None,
                                 compact_only: bool = False) -> dict[str, Any]:
        """Record and launch a turn while the admission/session locks are held."""
        turn_id = turn_id or _new_id("turn_")
        digest = digest or _digest(text)
        await session.log.append("request.accepted", request_id=request_id,
                                 turn_id=turn_id, text_digest=digest)
        session.request_ids[request_id] = (turn_id, digest)
        ready = asyncio.Event()
        session.stop_requested = False
        session.finishing = False
        task = asyncio.create_task(self._run_turn(session, turn_id, text, ready, compact_only=compact_only),
                                   name=f"agent:turn:{turn_id}")
        session.task = task
        self._turns[turn_id] = task
        session.status, session.turn_id = "running", turn_id
        # Stop/close cannot cancel a coroutine before it enters its cleanup scope.
        await ready.wait()
        return {"session_id": session.session_id, "turn_id": turn_id, "deduplicated": False}

    async def submit(self, session_id: str, text: str, *, request_id: str) -> dict[str, Any]:
        return await self._accept_message(session_id, text, request_id=request_id, queue=False)

    async def append(self, session_id: str, text: str, *, request_id: str) -> dict[str, Any]:
        """Append a user message at the next safe model boundary.

        An idle session starts a normal turn immediately.  A running session
        records a durable command and injects it after the current model and
        its complete tool group, within the same owned turn.
        """
        return await self._accept_message(session_id, text, request_id=request_id, queue=True)

    async def _accept_message(self, session_id: str, text: str, *,
                              request_id: str, queue: bool) -> dict[str, Any]:
        task = asyncio.create_task(
            self._admit_message(session_id, text, request_id=request_id, queue=queue),
            name=f"agent:admit:{session_id}",
        )
        self._admissions.add(task)
        task.add_done_callback(self._admission_done)
        return await asyncio.shield(task)

    def _admission_done(self, task: asyncio.Task) -> None:
        self._admissions.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None and not isinstance(error, LogAgentError):
                logger.error("Agent request admission failed", exc_info=error)

    async def _admit_message(self, session_id: str, text: str, *,
                             request_id: str, queue: bool) -> dict[str, Any]:
        """Serialize deduplication and publication for both message entrypoints."""
        if not isinstance(text, str) or not text.strip():
            raise LogAgentError("invalid_argument", "消息不能为空")
        if not isinstance(request_id, str) or not request_id.strip():
            raise LogAgentError("invalid_argument", "request_id 不能为空")
        session = self._session(session_id)
        digest = _digest(text)
        async with self._admission_lock:
            async with session.lock:
                previous = session.request_ids.get(request_id)
                if previous is not None:
                    if previous[1] != digest:
                        raise LogAgentError("request_conflict", "request_id 已用于其他消息")
                    return {"session_id": session_id, "turn_id": previous[0], "deduplicated": True}
                if not self._accepting:
                    raise LogAgentError("agent_busy", "Agent 当前暂停接收新轮次")
                if session.finishing and session.task is not None:
                    # The final model boundary is already closed. Wait for
                    # its durable terminal fact before accepting a new turn.
                    await asyncio.shield(session.task)
                if session.task is not None and not session.task.done():
                    if not queue:
                        raise LogAgentError("session_busy", "一个 session 同时只能运行一轮")
                    if session.stop_requested:
                        raise LogAgentError("session_busy", "停止中的轮次不再接收命令")
                    turn_id = session.turn_id
                    event = await session.log.append(
                        "command.queued", command="append", turn_id=session.turn_id,
                        queued_turn_id=turn_id, request_id=request_id,
                        text_digest=digest, text=text,
                    )
                    session.request_ids[request_id] = (turn_id, digest)
                    session.pending_appends.append((turn_id, text, request_id, digest))
                    return {"session_id": session_id, "turn_id": turn_id,
                            "status": "queued", "deduplicated": False,
                            "event_id": event["id"]}
                return await self._start_turn_locked(
                    session, text, request_id=request_id, digest=digest,
                )

    async def wait(self, turn_id: str) -> dict[str, Any]:
        task = self._turns.get(turn_id)
        if task is None:
            raise LogAgentError("turn_not_found", "Agent turn 不存在或已过期")
        return await asyncio.shield(task)

    async def cancel(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        task = session.task
        if task is None or task.done():
            return self._session_view(session)
        session.stop_requested = True
        if not task.cancelling():
            task.cancel()
        # The API acknowledges stop only after the turn has recorded its
        # terminal fact and released tool/scheduler resources.  A caller may
        # disconnect after this response without leaving a hidden background
        # cancellation race.
        await asyncio.shield(asyncio.gather(task, return_exceptions=True))
        return self._session_view(session)

    async def events(self, session_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        session = self._session(session_id)
        return await session.log.replay(after)

    def tool_views(self) -> list[dict[str, Any]]:
        """Return the published tool DTOs used by the next turn."""
        generation = self.plugins.generation if self.plugins is not None else None
        owners = ({item.name: item.plugin for item in self.plugins.toolRegister.describe()}
                  if self.plugins is not None else {})
        views = []
        for item in self._tool_declarations():
            # Registered tool descriptions carry their plugin owner.  Built-ins
            # are represented by their stable plugin IDs even when the service
            # is used without a PluginRegistry in tests or embedded callers.
            owner = owners.get(item.name, f"agent_{item.name}")
            schema = item.input_schema
            views.append({
                "name": item.name,
                "plugin": owner,
                "description": item.description,
                "execution": item.execution,
                "input_schema": schema,
                "definition_tokens": max(1, len(str(schema)) // 4),
                "generation": generation,
                "enabled": True,
            })
        if self.plugins is not None:
            published = {item["plugin"] for item in views}
            for plugin in self.plugins.toolRegister.plugins():
                if plugin["plugin"] not in published:
                    views.append({**plugin, "name": plugin["plugin"].removeprefix("agent_"),
                                  "description": "未注册；启用后显示实际定义", "execution": None,
                                  "input_schema": None, "definition_tokens": 0,
                                  "generation": generation, "registered": False})
        return views

    def update_config(self, config: AgentConfig) -> dict[str, Any]:
        """Publish configuration for subsequent turns."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.config_path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(config.model_dump_json(indent=2).encode())
                stream.flush()
                os.fsync(stream.fileno())
                os.replace(temporary, self.config_path)
            finally:
                temporary.unlink(missing_ok=True)
        self.config = config.model_copy(deep=True)
        return self.config.model_dump(mode="json")

    async def compact(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        async with self._admission_lock, session.lock:
            if not self._accepting:
                raise LogAgentError("agent_busy", "Agent 当前暂停接收命令")
            if session.task is not None and not session.task.done():
                if session.stop_requested:
                    raise LogAgentError("session_busy", "停止中的轮次不再接收命令")
                event = await session.log.append(
                    "command.queued", command="compact", turn_id=session.turn_id,
                )
                session.compact_pending = True
                session.compact_events.append(event["id"])
                return {"session_id": session_id, "status": "queued", "event_id": event["id"]}
            accepted = await self._start_turn_locked(
                session, "", request_id=_new_id("compact_"), compact_only=True,
            )
            return {**accepted, "status": "running"}

    async def _take_commands(self, session: AgentSession, *, final=False):
        async with session.lock:
            if session.stop_requested:
                raise asyncio.CancelledError
            session.finishing = final and not session.pending_appends
            if not session.pending_appends and not session.compact_pending:
                return None
            appends = list(session.pending_appends)
            compact_events = list(session.compact_events)
            session.pending_appends.clear()
            session.compact_pending = False
            session.compact_events.clear()
            additions = []
            for turn_id, text, request_id, digest in appends:
                message_id = _new_id("message_")
                await session.log.append("request.accepted", request_id=request_id,
                                         turn_id=turn_id, text_digest=digest)
                await session.log.append("message.user", turn_id=turn_id,
                                         text=text, message_id=message_id, request_id=request_id)
                additions.append(HumanMessage(content=text, id=message_id))

        async def complete(*, compacted):
            for _, _, request_id, _ in appends:
                await session.log.append("command.completed", command="append",
                                         turn_id=session.turn_id, request_id=request_id)
            for event_id in compact_events:
                await session.log.append("command.completed", command="compact",
                                         turn_id=session.turn_id, command_event_id=event_id,
                                         compacted=compacted)
        return additions, bool(compact_events), complete

    async def _cancel_pending_commands(self, session: AgentSession):
        for _, _, request_id, _ in session.pending_appends:
            await session.log.append("command.cancelled", command="append",
                                     turn_id=session.turn_id, request_id=request_id)
        for event_id in session.compact_events:
            await session.log.append("command.cancelled", command="compact",
                                     turn_id=session.turn_id, command_event_id=event_id)
        session.pending_appends.clear()
        session.compact_events.clear()
        session.compact_pending = False

    @asynccontextmanager
    async def _model(self, session: AgentSession, *, output_tokens: int,
                     ai_config=None, model: str | None = None):
        if self.model_provider is not None:
            value = self.model_provider(session)
            if inspect.isawaitable(value):
                value = await value
            if hasattr(value, "__aenter__"):
                async with value as model:
                    yield model
            else:
                yield value
            return
        ai_config = self.ai_config if ai_config is None else ai_config
        model = session.model if model is None else model
        if self.ai_service is None or ai_config is None or model is None:
            raise LogAgentError("model_unavailable", "Agent session 没有可用模型")
        async with self.ai_service.lease(
            ai_config, model=model, streaming=True,
            max_output_tokens=output_tokens,
        ) as model:
            yield model

    def _tool_declarations(self) -> tuple[ToolDeclaration, ...]:
        """Project the published tool registry into graph declarations."""
        if self.plugins is None:
            return tuple(self._declarations)
        declarations: list[ToolDeclaration] = []
        for description in self.plugins.toolRegister.describe():
            tool = self.plugins.toolRegister.get(description.name)
            if tool is None:
                continue
            declarations.append(ToolDeclaration(
                tool.name, tool.description, tool.input_schema, tool.execution, tool.invoke,
            ))
        return tuple(declarations)

    def _resolve_model(self, selected: str | None, snapshot: dict[str, Any]) -> tuple[Any, str]:
        """Resolve a model reference against one ResourceStore publication.

        A reference can be ``ai:model`` or ``ai/model``. Bare model names are
        accepted only when exactly one AI resource provides that name.
        """
        reference = selected or self.default_model
        candidates = [
            (ai_id, name, config)
            for ai_id, config in snapshot.get("ai", {}).items()
            for name in config.models
        ]
        if reference:
            separator = ":" if ":" in reference else "/" if "/" in reference else None
            if separator is not None:
                ai_id, name = reference.split(separator, 1)
                config = snapshot.get("ai", {}).get(ai_id)
                if config is not None and name in config.models:
                    return config, name
                raise LogAgentError("model_unavailable", "Agent session 引用的模型不可用",
                                    {"model": reference})
            matches = [(name, config) for _, name, config in candidates if name == reference]
            if len(matches) == 1:
                return matches[0][1], matches[0][0]
            if len(matches) > 1:
                raise LogAgentError("model_ambiguous", "模型名称对应多个 AI 资源",
                                    {"model": reference})
            raise LogAgentError("model_unavailable", "Agent session 引用的模型不可用",
                                {"model": reference})
        if len(candidates) == 1:
            return candidates[0][2], candidates[0][1]
        raise LogAgentError("model_unavailable", "Agent session 没有可用模型")

    def _capture_turn_resources(self, session: AgentSession) -> _TurnResources:
        config = self.config.model_copy(deep=True)
        declarations = tuple(replace(item, input_schema=deepcopy(item.input_schema))
                             for item in self._tool_declarations())
        if self.resources is None:
            return _TurnResources(config, deepcopy(self.ai_config), session.model,
                                  None, None, None, declarations, None)
        snapshot = self.resources.invocation_snapshot()
        ai_config = None
        model_name = session.model
        summary_ai_config = None
        summary_model = None
        if self.model_provider is None:
            ai_config, model_name = self._resolve_model(session.model, snapshot)
            if config.summary_ai is not None:
                summary_ai_config, summary_model = self._resolve_summary_model(
                    config.summary_ai, model_name, snapshot,
                )
        if self.gateway_factory is not None:
            gateway = self.gateway_factory(session)
        elif self.plugins is not None and self.collectors is not None and self.channels is not None:
            gateway = PluginGateway(
                InvocationSnapshot(
                    self.plugins.generation, snapshot, self.plugins.collectorRegister,
                    self.plugins.channelRegister, self.plugins.toolRegister,
                ),
                collectors=self.collectors, channels=self.channels,
                data_dir=Path(getattr(self.resources, "_data_dir", self.workspace.root)),
            )
        else:
            gateway = None
        return _TurnResources(
            config, ai_config, model_name, summary_ai_config, summary_model,
            self.plugins.generation if self.plugins is not None else None,
            declarations, gateway,
        )

    @staticmethod
    def _resolve_summary_model(reference: str, main_model: str | None,
                               snapshot: dict[str, Any]) -> tuple[Any, str]:
        """Select a model from the configured summary AI resource.

        ``summary_ai`` names an AI resource rather than duplicating a second model
        selector in AgentConfig.  Reuse the main model when that resource exposes
        it; otherwise use its first configured model in stable order.  An empty
        or unknown resource is an explicit configuration error.
        """
        config = snapshot.get("ai", {}).get(reference)
        if config is None:
            raise LogAgentError("model_unavailable", "Agent 摘要模型资源不可用",
                                {"summary_ai": reference})
        if main_model is not None and main_model in config.models:
            return config, main_model
        names = sorted(config.models)
        if not names:
            raise LogAgentError("model_unavailable", "Agent 摘要模型资源没有可用模型",
                                {"summary_ai": reference})
        return config, names[0]

    @staticmethod
    def _message_delta(chunk: Any) -> dict[str, Any] | None:
        """Project one LangChain chat stream chunk into a durable small delta.

        The event log stores only emitted text/tool-call fragments.  It never
        fabricates a token when a provider emits no stream event, and it keeps
        provider-specific metadata out of the public event payload.
        """
        content = getattr(chunk, "content", None)
        tool_calls = getattr(chunk, "tool_call_chunks", None) or getattr(chunk, "tool_calls", None)
        delta: dict[str, Any] = {}
        if isinstance(content, str) and content:
            delta["content"] = content
        elif isinstance(content, list) and content:
            delta["content"] = content
        if tool_calls:
            delta["tool_calls"] = tool_calls
        return delta or None

    async def _stream_graph(self, graph: Any, messages: list[Any], *, session: AgentSession,
                            turn_id: str, log: EventLog, idle_timeout: float,
                            publication: list[bool] | None = None) -> tuple[dict[str, Any], bool]:
        """Consume graph events while enforcing the model inactivity boundary.

        ``astream_events`` is used instead of a second graph invocation so a
        provider's true incremental chunks are persisted exactly once.  A
        timeout while waiting for an event is an upstream model idle timeout;
        heartbeat events from the HTTP layer never enter this loop.
        """
        stream = graph.astream_events(
            {"messages": messages},
            {"configurable": {"thread_id": session.session_id}},
            version="v2",
        )
        final_state: dict[str, Any] | None = None
        published = False
        awaiting_model = False
        try:
            while True:
                if awaiting_model:
                    try:
                        event = await asyncio.wait_for(
                            stream.__anext__(), timeout=idle_timeout,
                        )
                    except StopAsyncIteration:
                        break
                    except TimeoutError as exc:
                        raise LogAgentError(
                            "model_idle_timeout", "模型流式输出在无活动超时内没有新事件",
                            {"idle_timeout": idle_timeout},
                        ) from exc
                else:
                    try:
                        event = await stream.__anext__()
                    except StopAsyncIteration:
                        break

                event_name = event.get("event") if isinstance(event, dict) else None
                if event_name == "on_chat_model_start":
                    awaiting_model = True
                is_summary = event.get("metadata", {}).get("lc_source") == "summarization"
                if event_name == "on_chat_model_stream" and not is_summary:
                    data = event.get("data", {})
                    delta = self._message_delta(data.get("chunk")) if isinstance(data, dict) else None
                    if delta is not None:
                        published = True
                        if publication is not None:
                            publication[0] = True
                        await log.append(
                            "message.delta", turn_id=turn_id,
                            message_id=getattr(data.get("chunk"), "id", None),
                            **delta,
                        )
                if event_name == "on_chat_model_end":
                    awaiting_model = False
                if event_name == "on_chain_end" and isinstance(event.get("data"), dict):
                    output = event["data"].get("output")
                    if isinstance(output, dict) and isinstance(output.get("messages"), list):
                        final_state = output
        except BaseException as exc:
            # Preserve the original provider error while carrying the durable
            # publication boundary to the turn terminal event.
            try:
                exc._agent_published = published
            except Exception:
                pass
            raise
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        if final_state is None:
            raise LogAgentError("invalid_response", "Agent 图没有返回最终消息状态")
        return final_state, published

    @staticmethod
    async def _cancel_tools(context: AgentToolContext | None) -> None:
        """Cancel and await in-flight tools before a cancelled turn returns."""
        if context is None or not context.tool_tasks:
            return
        tasks = list(context.tool_tasks.values())
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                raise result

    @asynccontextmanager
    async def _tool_scope(self, context: AgentToolContext):
        try:
            yield
        finally:
            await self._cancel_tools(context)

    async def _run_turn(self, session: AgentSession, turn_id: str, text: str,
                        ready: asyncio.Event, *, compact_only: bool = False) -> dict[str, Any]:
        had_previous_turn = any(event["type"].startswith("turn.") for event in session.log.events)
        session.status, session.turn_id = "running", turn_id
        session.updated_at = datetime.now(UTC).isoformat()
        log = session.log
        context = None
        published = False
        publication = [False]
        try:
            ready.set()
            turn_resources = self._capture_turn_resources(session)
            config = turn_resources.config
            await self.scheduler.resize(config.read_concurrency)
            message_id = _new_id("message_")
            if not compact_only:
                await log.append("message.user", turn_id=turn_id, text=text, message_id=message_id)
            await log.append("turn.started", turn_id=turn_id, branch_id=session.branch_id)
            await log.append("turn.resources", turn_id=turn_id, model=turn_resources.model,
                             tools_generation=turn_resources.tools_generation)
            identity = RuntimeIdentity(
                session.session_id, turn_id, session.branch_id,
                workflow_session_id=session.workflow_session_id, model=turn_resources.model,
                tools_generation=turn_resources.tools_generation,
                workspace=str(self.workspace.root),
            )
            view = self.workspace.for_identity(identity)
            if turn_resources.gateway is not None:
                await turn_resources.gateway.catalog(view, revision=turn_id)
            instructions = await view.instructions()
            system_prompt = build_system_prompt(
                agents=instructions, session_id=session.session_id, branch_id=session.branch_id,
                turn_id=turn_id, workspace=str(view.root),
                workflow_session_id=session.workflow_session_id, now=datetime.now(ZoneInfo(config.timezone)),
            )
            context = AgentToolContext(
                workspace=view, sandbox=ShellSandbox(view), gateway=turn_resources.gateway,
                config=config,
                session_id=session.session_id, turn_id=turn_id, branch_id=session.branch_id,
                event_log=log, scheduler=self.scheduler, artifacts=self.artifacts,
                read_enabled=any(item.name == "read" for item in turn_resources.declarations),
                on_boundary=lambda **kwargs: self._take_commands(session, **kwargs),
                collection=(self.collection_context_factory(session)
                            if self.collection_context_factory is not None
                            else CollectionContext("agent", session.session_id)),
            )
            messages = []
            if not compact_only and session.workflow_input is not None and not any(
                event["type"] == "workflow.input.used" for event in log.events
            ):
                messages.append(HumanMessage(content=json.dumps(
                    {"input": session.workflow_input}, ensure_ascii=False, sort_keys=True)))
                await log.append("workflow.input.used", turn_id=turn_id)
            if not compact_only:
                messages.append(HumanMessage(content=text, id=message_id))
            await self._ensure_checkpoint_present(
                session, require_existing=had_previous_turn,
            )
            timeout_seconds = getattr(turn_resources.ai_config, "timeout", None)
            timeout_context = (
                asyncio.timeout(timeout_seconds)
                if timeout_seconds is not None else None
            )
            if timeout_context is None:
                timeout_context = _null_async_context()
            async with timeout_context:
                async with self._model(session, ai_config=turn_resources.ai_config,
                                       model=turn_resources.model,
                                       output_tokens=config.output_tokens) as model:
                    separate_summary = (turn_resources.summary_ai_config is not None
                                        or config.summary_max_tokens != config.output_tokens)
                    if separate_summary and self.model_provider is None:
                        summary_context = self._model(
                            session, ai_config=(turn_resources.summary_ai_config
                                                or turn_resources.ai_config),
                            model=turn_resources.summary_model or turn_resources.model,
                            output_tokens=config.summary_max_tokens,
                        )
                    else:
                        summary_context = _null_async_context(model)
                    async with summary_context as summary_model, self._tool_scope(context):
                        graph = create_graph(
                            model=model, summary_model=summary_model,
                            summary_timeout=(
                                getattr(turn_resources.summary_ai_config, "timeout", None)
                                if turn_resources.summary_ai_config is not None else None
                            ),
                            declarations=turn_resources.declarations,
                            context=context, system_prompt=system_prompt,
                            checkpointer=self.checkpointer,
                        )
                        await self._prepare_checkpoint(
                            session, graph, log, turn_id, require_existing=had_previous_turn,
                        )
                        graph_config = {"configurable": {"thread_id": session.session_id}}
                        if compact_only:
                            state = await graph.aget_state(graph_config)
                            update = await context.context_middleware.prepare(
                                state.values.get("messages", []), force=True,
                            )
                            if update or not state.config.get("configurable", {}).get("checkpoint_id"):
                                await self._projection_graph().aupdate_state(
                                    graph_config, update or {"messages": []}, as_node="projection",
                                )
                            await log.append("command.completed", command="compact", turn_id=turn_id,
                                             compacted=update is not None)
                            result = {"messages": []}
                        else:
                            result, published = await self._stream_graph(
                                graph, messages, session=session, turn_id=turn_id, log=log,
                                publication=publication, idle_timeout=config.idle_timeout,
                            )
                        state = await graph.aget_state(graph_config)
                        checkpoint_id = state.config.get("configurable", {}).get("checkpoint_id")
            answer = "" if compact_only else _last_text(result)
            completed = {"turn_id": turn_id, "incremental": published}
            if not published:
                completed["text"] = answer
            if not compact_only:
                await log.append("message.completed", **completed)
            await self._cancel_pending_commands(session)
            await log.append("turn.completed", turn_id=turn_id, text=answer,
                             checkpoint_id=checkpoint_id, command="compact" if compact_only else None)
            session.status = "completed"
            return {"turn_id": turn_id, "status": "completed", "text": answer}
        except asyncio.CancelledError:
            published = published or publication[0]
            await self._cancel_pending_commands(session)
            await log.append("turn.cancelled", turn_id=turn_id, partial=published)
            session.status = "cancelled"
            raise
        except TimeoutError as exc:
            published = bool(getattr(exc, "_agent_published", published or publication[0]))
            await self._cancel_pending_commands(session)
            await log.append(
                "turn.failed", turn_id=turn_id,
                error={"code": "ai_timeout", "message": "模型调用总时限已耗尽"},
                partial=published,
            )
            session.status = "failed"
            raise LogAgentError("ai_timeout", "模型调用总时限已耗尽",
                                {"timeout": getattr(turn_resources.ai_config, "timeout", None)}) from exc
        except Exception as exc:
            published = bool(getattr(exc, "_agent_published", published or publication[0]))
            await self._cancel_pending_commands(session)
            error = (exc.info.model_dump(mode="json") if isinstance(exc, LogAgentError)
                     else {"type": type(exc).__name__, "message": str(exc)})
            await log.append("turn.failed", turn_id=turn_id,
                             error=error, partial=published)
            session.status = "failed"
            raise
        finally:
            session.updated_at = log.events[-1]["created_at"]
            await self._persist_session(session)

    async def _ensure_checkpoint_present(self, session: AgentSession, *,
                                         require_existing: bool) -> None:
        """Fail before leasing a model when a historical thread has no state."""
        if not require_existing or self.checkpointer is None:
            return
        getter = getattr(self.checkpointer, "aget_tuple", None)
        if getter is None:
            return
        try:
            checkpoint = await getter({"configurable": {"thread_id": session.session_id}})
        except Exception as exc:
            raise LogAgentError(
                "checkpoint_corrupt", "Agent checkpoint 无法读取，不能继续会话",
                {"exception_type": type(exc).__name__},
            ) from exc
        if checkpoint is None:
            raise LogAgentError(
                "checkpoint_missing", "Agent checkpoint 缺失，不能猜测历史继续",
                {"session_id": session.session_id},
            )

    async def _prepare_checkpoint(self, session: AgentSession, graph: Any,
                                  log: EventLog, turn_id: str, *,
                                  require_existing: bool) -> None:
        """Validate the previous thread state and close an interrupted tool step.

        Event JSONL tells us which side effects are complete or unknown.  The
        LangGraph checkpoint only supplies the pending message boundary.  If
        either source is unavailable we stop explicitly instead of rebuilding
        a plausible state and risking a duplicate side effect.
        """
        config = {"configurable": {"thread_id": session.session_id}}
        try:
            state = await graph.aget_state(config)
        except Exception as exc:
            raise LogAgentError(
                "checkpoint_corrupt", "Agent checkpoint 无法读取，不能继续会话",
                {"exception_type": type(exc).__name__},
            ) from exc

        if state is None:
            if require_existing:
                raise LogAgentError(
                    "checkpoint_missing", "Agent checkpoint 缺失，不能猜测历史继续",
                    {"session_id": session.session_id},
                )
            return

        values = getattr(state, "values", None) or {}
        messages = values.get("messages", []) if isinstance(values, dict) else []
        next_nodes = tuple(getattr(state, "next", ()) or ())
        checkpoint_id = (getattr(state, "config", None) or {}).get("configurable", {}).get("checkpoint_id")
        if require_existing and not messages and not next_nodes and not checkpoint_id:
            raise LogAgentError(
                "checkpoint_missing", "Agent checkpoint 缺失，不能猜测历史继续",
                {"session_id": session.session_id},
            )
        if not next_nodes:
            return

        pending: list[str] = []
        replied: set[str] = set()
        for message in messages:
            tool_call_id = getattr(message, "tool_call_id", None)
            if isinstance(tool_call_id, str):
                replied.add(tool_call_id)
        for message in messages:
            for call in getattr(message, "tool_calls", ()) or ():
                call_id = call.get("id") if isinstance(call, dict) else None
                if isinstance(call_id, str) and call_id not in replied:
                    pending.append(call_id)

        if not pending:
            raise LogAgentError(
                "checkpoint_corrupt", "Agent checkpoint 存在未完成节点但没有可修复工具调用",
                {"next": list(next_nodes)},
            )
        if "tools" not in next_nodes:
            raise LogAgentError(
                "checkpoint_corrupt", "Agent checkpoint 的未完成节点不是工具边界",
                {"next": list(next_nodes)},
            )

        repairs = [ToolMessage(
            content=json.dumps({"status": "outcome_unknown", "reason": "interrupted"},
                               ensure_ascii=False, sort_keys=True),
            tool_call_id=call_id,
        ) for call_id in pending]
        try:
            await graph.aupdate_state(config, {"messages": repairs}, as_node="tools")
            await graph.aupdate_state(config, None, as_node=END)
        except Exception as exc:
            raise LogAgentError(
                "checkpoint_corrupt", "Agent checkpoint 无法写入中断工具结果",
                {"exception_type": type(exc).__name__},
            ) from exc
        await log.append("checkpoint.repaired", turn_id=turn_id,
                         tool_call_ids=pending, result="outcome_unknown")


def _last_text(result: dict[str, Any]) -> str:
    for message in reversed(result.get("messages", [])):
        if isinstance(message, AIMessage) and isinstance(message.content, str):
            return message.content
    raise LogAgentError("invalid_response", "Agent 没有返回文本消息")


def _digest(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
