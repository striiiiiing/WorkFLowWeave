"""Long-lived Agent sessions backed by LangGraph and the event log."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import shutil
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END

from logagent.agent.artifacts import ArtifactStore
from logagent.agent.builtin import grep, plugin, read, shell, write
from logagent.agent.builtin.declaration import ToolDeclaration
from logagent.agent.config import AgentConfig
from logagent.agent.context import build_system_prompt, validate_request_budget
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
    parent_session_id: str | None = None
    parent_turn_id: str | None = None
    parent_branch_id: str | None = None
    pending_appends: list[tuple[str, str, str, str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _TurnResources:
    """Resources captured before a turn and never changed during that turn."""

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
        self.config = config or AgentConfig()
        self.workspace = WorkspaceBackend(workspace, runtime)
        self.runtime = Path(runtime).absolute()
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
        await self.workspace.initialize()
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
                    session.pending_appends.append((queued_turn, text, request_id, digest))
                    session.request_ids[request_id] = (queued_turn, digest)
            for event in log.events:
                if event["type"] == "request.accepted":
                    request_id = event.get("request_id")
                    digest = event.get("text_digest")
                    accepted_turn = event.get("turn_id")
                    if isinstance(request_id, str) and isinstance(digest, str) \
                            and isinstance(accepted_turn, str):
                        session.request_ids[request_id] = (accepted_turn, digest)
            self.sessions[directory.name] = session

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
                             parent_branch_id: str | None = None) -> dict[str, Any]:
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
                parent_branch_id=parent_branch_id,
            )
            await session.log.initialize()
            created = await session.log.append(
                "session.created", branch_id=session.branch_id,
                model=session.model, workflow_session_id=workflow_session_id,
                parent_session_id=parent_session_id, parent_turn_id=parent_turn_id,
                parent_branch_id=parent_branch_id,
            )
            if workflow_result is not None:
                await session.log.append("workflow.input", workflow_session_id=workflow_session_id,
                                         input=workflow_result)
            session.created_at = created["created_at"]
            session.updated_at = session.log.events[-1]["created_at"]
            self.sessions[sid] = session
            return self._session_view(session)

    async def _copy_checkpoint_thread(self, source_session_id: str,
                                      target_session_id: str) -> None:
        """Copy a complete SQLite checkpoint chain for a fork.

        The installed AsyncSqliteSaver exposes ``acopy_thread`` only as an
        abstract placeholder.  Its public async cursor and serializer-backed
        tables are stable in the supported version, so copy every namespace,
        checkpoint and pending write in one transaction.  Unknown saver
        implementations fail explicitly instead of creating a branch with a
        missing context.
        """
        saver = self.checkpointer
        if saver is None or not hasattr(saver, "conn") or not hasattr(saver, "lock"):
            raise LogAgentError("checkpoint_fork_unavailable", "当前 checkpoint 不支持安全分支")
        await saver.setup()
        async with saver.lock, saver.conn.cursor() as cursor:
            await cursor.execute(
                "SELECT checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata "
                "FROM checkpoints WHERE thread_id = ? ORDER BY checkpoint_ns, checkpoint_id",
                (source_session_id,),
            )
            checkpoints = await cursor.fetchall()
            if not checkpoints:
                raise LogAgentError("checkpoint_missing", "源会话 checkpoint 缺失，不能创建分支")
            await cursor.execute(
                "SELECT checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value "
                "FROM writes WHERE thread_id = ? ORDER BY checkpoint_ns, checkpoint_id, task_id, idx",
                (source_session_id,),
            )
            writes = await cursor.fetchall()
            await cursor.executemany(
                "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(target_session_id, *row) for row in checkpoints],
            )
            await cursor.executemany(
                "INSERT INTO writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(target_session_id, *row) for row in writes],
            )
            await saver.conn.commit()

    async def fork(self, session_id: str, *, turn_id: str | None = None,
                   model: str | None = None) -> dict[str, Any]:
        """Create a read-only parent branch and a new session at its checkpoint."""
        source = self._session(session_id)
        if source.task is not None and not source.task.done():
            raise LogAgentError("session_busy", "运行中的 session 不能创建分支")
        selected_turn = turn_id or source.turn_id
        if selected_turn is not None and not any(
                event.get("turn_id") == selected_turn
                and event["type"] in {"turn.completed", "turn.failed", "turn.cancelled", "turn.interrupted"}
                for event in source.log.events):
            raise LogAgentError("turn_not_found", "分支起点轮次不存在或尚未结束")
        child = await self.create_session(
            model=model or source.model,
            workflow_session_id=source.workflow_session_id,
            parent_session_id=source.session_id,
            parent_turn_id=selected_turn,
            parent_branch_id=source.branch_id,
        )
        try:
            await self._copy_checkpoint_thread(source.session_id, child["session_id"])
        except Exception:
            self.sessions.pop(child["session_id"], None)
            shutil.rmtree(self.runtime / "History" / child["session_id"], ignore_errors=True)
            raise
        child_session = self.sessions[child["session_id"]]
        await child_session.log.append(
            "branch.created", parent_session_id=source.session_id,
            parent_turn_id=selected_turn, parent_branch_id=source.branch_id,
        )
        return self._session_view(child_session)

    def _session_view(self, session: AgentSession) -> dict[str, Any]:
        return {"session_id": session.session_id, "branch_id": session.branch_id,
                "model": session.model, "workflow_session_id": session.workflow_session_id,
                "parent_session_id": session.parent_session_id,
                "parent_turn_id": session.parent_turn_id,
                "parent_branch_id": session.parent_branch_id,
                "created_at": session.created_at, "updated_at": session.updated_at,
                "status": session.status, "turn_id": session.turn_id}

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
                                 digest: str | None = None) -> dict[str, Any]:
        """Record and launch a turn while the admission/session locks are held."""
        turn_id = turn_id or _new_id("turn_")
        digest = digest or _digest(text)
        await session.log.append("request.accepted", request_id=request_id,
                                 turn_id=turn_id, text_digest=digest)
        session.request_ids[request_id] = (turn_id, digest)
        ready = asyncio.Event()
        task = asyncio.create_task(self._run_turn(session, turn_id, text, ready),
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
        records a durable command and starts the queued turn only after the
        current turn has reached a terminal event.
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
                if session.task is not None and not session.task.done():
                    if not queue:
                        raise LogAgentError("session_busy", "一个 session 同时只能运行一轮")
                    turn_id = _new_id("turn_")
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
        async with session.lock:
            task = session.task
            if task is None or task.done():
                return self._session_view(session)
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
        return views

    def update_config(self, config: AgentConfig) -> dict[str, Any]:
        """Publish configuration for subsequent turns."""
        self.config = config
        self.scheduler = ToolScheduler(config.read_concurrency)
        return config.model_dump(mode="json")

    async def compact(self, session_id: str) -> dict[str, Any]:
        """Queue a compact command at a running turn's next safe boundary.

        The first implementation records the command durably; an idle session
        with no compactable checkpoint is an explicit no-op rather than a
        fabricated summary.
        """
        session = self._session(session_id)
        async with session.lock:
            if session.task is not None and not session.task.done():
                session.compact_pending = True
                event = await session.log.append(
                    "command.queued", command="compact", turn_id=session.turn_id,
                )
                return {"session_id": session_id, "status": "queued", "event_id": event["id"]}
            event = await session.log.append(
                "context.compacted", turn_id=session.turn_id, empty=True,
            )
            return {"session_id": session_id, "status": "completed", "empty": True,
                    "event_id": event["id"]}

    async def _drain_append(self, session: AgentSession,
                            *, finishing_task: asyncio.Task | None = None) -> None:
        """Start one queued append after the current turn terminal fact."""
        if not self._accepting:
            return
        async with self._admission_lock:
            if not self._accepting:
                return
            async with session.lock:
                if not session.pending_appends:
                    return
                if session.task is finishing_task:
                    session.task = None
                if session.task is not None and not session.task.done():
                    return
                turn_id, text, request_id, digest = session.pending_appends.pop(0)
                await self._start_turn_locked(
                    session, text, request_id=request_id,
                    turn_id=turn_id, digest=digest,
                )

    @asynccontextmanager
    async def _model(self, session: AgentSession, *, ai_config=None, model: str | None = None):
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
            max_output_tokens=self.config.output_tokens,
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
        declarations = self._tool_declarations()
        if self.resources is None:
            return _TurnResources(self.ai_config, session.model, None, None, None, declarations, None)
        snapshot = self.resources.invocation_snapshot()
        ai_config = None
        model_name = session.model
        summary_ai_config = None
        summary_model = None
        if self.model_provider is None:
            ai_config, model_name = self._resolve_model(session.model, snapshot)
            if self.config.summary_ai is not None:
                summary_ai_config, summary_model = self._resolve_summary_model(
                    self.config.summary_ai, model_name, snapshot,
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
            ai_config, model_name, summary_ai_config, summary_model,
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
                            turn_id: str, log: EventLog,
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
                            stream.__anext__(), timeout=self.config.idle_timeout,
                        )
                    except StopAsyncIteration:
                        break
                    except TimeoutError as exc:
                        raise LogAgentError(
                            "model_idle_timeout", "模型流式输出在无活动超时内没有新事件",
                            {"idle_timeout": self.config.idle_timeout},
                        ) from exc
                else:
                    try:
                        event = await stream.__anext__()
                    except StopAsyncIteration:
                        break

                event_name = event.get("event") if isinstance(event, dict) else None
                if event_name == "on_chat_model_start":
                    awaiting_model = True
                if event_name == "on_chat_model_stream":
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
                        ready: asyncio.Event) -> dict[str, Any]:
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
            await log.append("message.user", turn_id=turn_id, text=text)
            await log.append("turn.started", turn_id=turn_id, branch_id=session.branch_id)
            identity = RuntimeIdentity(
                session.session_id, turn_id, session.branch_id,
                workflow_session_id=session.workflow_session_id, model=session.model,
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
                workflow_session_id=session.workflow_session_id, now=datetime.now(UTC),
            )
            context = AgentToolContext(
                workspace=view, sandbox=ShellSandbox(view), gateway=turn_resources.gateway,
                config=self.config,
                session_id=session.session_id, turn_id=turn_id, branch_id=session.branch_id,
                event_log=log, scheduler=self.scheduler, artifacts=self.artifacts,
                collection=(self.collection_context_factory(session)
                            if self.collection_context_factory is not None
                            else CollectionContext("agent", session.session_id)),
            )
            messages = []
            if session.workflow_input is not None and not any(
                event["type"] == "workflow.input.used" for event in log.events
            ):
                messages.append(HumanMessage(content=json.dumps(
                    {"input": session.workflow_input}, ensure_ascii=False, sort_keys=True)))
                await log.append("workflow.input.used", turn_id=turn_id)
            messages.append(HumanMessage(content=text))
            validate_request_budget(
                messages, system_prompt,
                [{"name": item.name, "description": item.description,
                  "input_schema": item.input_schema} for item in turn_resources.declarations],
                self.config,
            )
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
                                       model=turn_resources.model) as model:
                    if turn_resources.summary_ai_config is not None:
                        summary_context = self._model(
                            session, ai_config=turn_resources.summary_ai_config,
                            model=turn_resources.summary_model,
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
                        result, published = await self._stream_graph(
                            graph, messages, session=session, turn_id=turn_id, log=log,
                            publication=publication,
                        )
            if session.compact_pending:
                await log.append("context.compacted", turn_id=turn_id, empty=True)
                session.compact_pending = False
            answer = _last_text(result)
            completed = {"turn_id": turn_id, "incremental": published}
            if not published:
                completed["text"] = answer
            await log.append("message.completed", **completed)
            await log.append("turn.completed", turn_id=turn_id, text=answer)
            session.status = "completed"
            return {"turn_id": turn_id, "status": "completed", "text": answer}
        except asyncio.CancelledError:
            published = published or publication[0]
            session.status = "cancelled"
            await log.append("turn.cancelled", turn_id=turn_id, partial=published)
            raise
        except TimeoutError as exc:
            published = bool(getattr(exc, "_agent_published", published or publication[0]))
            session.status = "failed"
            await log.append(
                "turn.failed", turn_id=turn_id,
                error={"code": "ai_timeout", "message": "模型调用总时限已耗尽"},
                partial=published,
            )
            raise LogAgentError("ai_timeout", "模型调用总时限已耗尽",
                                {"timeout": getattr(turn_resources.ai_config, "timeout", None)}) from exc
        except Exception as exc:
            published = bool(getattr(exc, "_agent_published", published or publication[0]))
            session.status = "failed"
            await log.append("turn.failed", turn_id=turn_id,
                             error={"type": type(exc).__name__, "message": str(exc)},
                             partial=published)
            raise
        finally:
            session.updated_at = log.events[-1]["created_at"]
            await self._drain_append(session, finishing_task=asyncio.current_task())

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
        if require_existing and not messages and not next_nodes:
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
