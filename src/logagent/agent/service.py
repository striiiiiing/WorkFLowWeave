"""Long-lived Agent sessions backed by LangGraph and the event log."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from logagent.agent.artifacts import ArtifactStore
from logagent.agent.builtin import grep, plugin, read, shell, write
from logagent.agent.builtin.declaration import ToolDeclaration
from logagent.agent.config import AgentConfig
from logagent.agent.context import build_system_prompt, validate_request_budget
from logagent.agent.events import EventLog
from logagent.agent.graph import AgentToolContext, create_graph
from logagent.agent.sandbox import ShellSandbox
from logagent.agent.scheduling import ToolScheduler
from logagent.agent.workspace import RuntimeIdentity, WorkspaceBackend
from logagent.errors import LogAgentError

ModelProvider = Callable[["AgentSession"], Any]


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


def _new_id(prefix: str = "") -> str:
    value = prefix + uuid4().hex
    return value[:80]


class AgentService:
    """Own all Agent session tasks while sharing one workspace scheduler."""

    def __init__(self, workspace: Path, runtime: Path, *, config: AgentConfig | None = None,
                 model_provider: ModelProvider | None = None, ai_service=None,
                 ai_config=None, model: str | None = None, checkpointer=None,
                 declarations: list[ToolDeclaration] | None = None,
                 gateway_factory: Callable[[AgentSession], Any] | None = None,
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
        self.checkpointer = checkpointer
        self._checkpointer_context = None
        self._owns_checkpointer = checkpointer is None
        self.gateway_factory = gateway_factory
        self._declarations = declarations or [plugin.plugin, read.plugin, write.plugin,
                                               grep.plugin, shell.plugin]
        if read_only_tools:
            self._declarations = [item for item in self._declarations if item.execution == "read"]
        self.sessions: dict[str, AgentSession] = {}
        self._turns: dict[str, asyncio.Task] = {}
        self._initialized = False

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
            status = "interrupted" if terminal and terminal["type"] == "turn.started" else "created"
            if terminal is not None and terminal["type"] == "turn.completed":
                status = "completed"
            elif terminal is not None and terminal["type"] == "turn.cancelled":
                status = "cancelled"
            elif terminal is not None and terminal["type"] == "turn.failed":
                status = "failed"
            turn_id = terminal.get("turn_id") if terminal else None
            await log.recover_interrupted()
            now = created["created_at"]
            self.sessions[directory.name] = AgentSession(
                directory.name, created.get("branch_id", _new_id("branch_")),
                created.get("model"), created.get("workflow_session_id"),
                workflow.get("input") if workflow else None, now, now,
                status=status, turn_id=turn_id, log=log,
            )

    async def close(self) -> None:
        tasks = [task for task in self._turns.values() if not task.done()]
        for task in tasks:
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
                             session_id: str | None = None) -> dict[str, Any]:
        await self.initialize()
        sid = session_id or _new_id("agent_")
        if sid in self.sessions:
            raise LogAgentError("session_conflict", "Agent session 已存在")
        now = datetime.now(UTC).isoformat()
        session = AgentSession(
            sid, _new_id("branch_"), model or self.default_model,
            workflow_session_id, workflow_result, now, now,
            log=EventLog(self.runtime, sid),
        )
        await session.log.initialize()
        self.sessions[sid] = session
        await session.log.append("session.created", branch_id=session.branch_id,
                                 model=session.model, workflow_session_id=workflow_session_id)
        if workflow_result is not None:
            await session.log.append("workflow.input", workflow_session_id=workflow_session_id,
                                     input=workflow_result)
        return self._session_view(session)

    def _session_view(self, session: AgentSession) -> dict[str, Any]:
        return {"session_id": session.session_id, "branch_id": session.branch_id,
                "model": session.model, "workflow_session_id": session.workflow_session_id,
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

    async def submit(self, session_id: str, text: str, *, request_id: str) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise LogAgentError("invalid_argument", "消息不能为空")
        if not isinstance(request_id, str) or not request_id.strip():
            raise LogAgentError("invalid_argument", "request_id 不能为空")
        session = self._session(session_id)
        digest = _digest(text)
        previous = session.request_ids.get(request_id)
        if previous is not None:
            if previous[1] != digest:
                raise LogAgentError("request_conflict", "request_id 已用于其他消息")
            return {"session_id": session_id, "turn_id": previous[0], "deduplicated": True}
        async with session.lock:
            if session.task is not None and not session.task.done():
                raise LogAgentError("session_busy", "一个 session 同时只能运行一轮")
            turn_id = _new_id("turn_")
            session.request_ids[request_id] = (turn_id, digest)
            task = asyncio.create_task(self._run_turn(session, turn_id, text),
                                       name=f"agent:turn:{turn_id}")
            session.task = task
            self._turns[turn_id] = task
        return {"session_id": session_id, "turn_id": turn_id, "deduplicated": False}

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
        task.cancel()
        return self._session_view(session)

    async def events(self, session_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        session = self._session(session_id)
        return await session.log.replay(after)

    @asynccontextmanager
    async def _model(self, session: AgentSession):
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
        if self.ai_service is None or self.ai_config is None or session.model is None:
            raise LogAgentError("model_unavailable", "Agent session 没有可用模型")
        async with self.ai_service.lease(
            self.ai_config, model=session.model, streaming=True,
            max_output_tokens=self.config.output_tokens,
        ) as model:
            yield model

    async def _run_turn(self, session: AgentSession, turn_id: str, text: str) -> dict[str, Any]:
        session.status, session.turn_id = "running", turn_id
        session.updated_at = datetime.now(UTC).isoformat()
        log = session.log
        await log.append("turn.started", turn_id=turn_id, branch_id=session.branch_id)
        identity = RuntimeIdentity(
            session.session_id, turn_id, session.branch_id,
            workflow_session_id=session.workflow_session_id, model=session.model,
            workspace=str(self.workspace.root),
        )
        view = self.workspace.for_identity(identity)
        context = None
        try:
            instructions = await view.instructions()
            system_prompt = build_system_prompt(
                agents=instructions, session_id=session.session_id, branch_id=session.branch_id,
                turn_id=turn_id, workspace=str(view.root),
                workflow_session_id=session.workflow_session_id, now=datetime.now(UTC),
            )
            context = AgentToolContext(
                workspace=view, sandbox=ShellSandbox(view), gateway=self.gateway_factory(session)
                if self.gateway_factory else None, config=self.config,
                session_id=session.session_id, turn_id=turn_id, branch_id=session.branch_id,
                event_log=log, scheduler=self.scheduler, artifacts=self.artifacts,
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
                  "input_schema": item.input_schema} for item in self._declarations],
                self.config,
            )
            async with self._model(session) as model:
                graph = create_graph(model=model, declarations=self._declarations,
                                     context=context, system_prompt=system_prompt,
                                     checkpointer=self.checkpointer)
                result = await graph.ainvoke(
                    {"messages": messages},
                    {"configurable": {"thread_id": session.session_id}},
                )
            answer = _last_text(result)
            session.status = "completed"
            await log.append("turn.completed", turn_id=turn_id, text=answer)
            return {"turn_id": turn_id, "status": "completed", "text": answer}
        except asyncio.CancelledError:
            session.status = "cancelled"
            await log.append("turn.cancelled", turn_id=turn_id)
            raise
        except Exception as exc:
            session.status = "failed"
            await log.append("turn.failed", turn_id=turn_id,
                             error={"type": type(exc).__name__, "message": str(exc)})
            raise
        finally:
            session.updated_at = datetime.now(UTC).isoformat()


def _last_text(result: dict[str, Any]) -> str:
    for message in reversed(result.get("messages", [])):
        if isinstance(message, AIMessage) and isinstance(message.content, str):
            return message.content
    raise LogAgentError("invalid_response", "Agent 没有返回文本消息")


def _digest(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
