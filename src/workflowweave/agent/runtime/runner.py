"""Prepare, execute and finalize one LangGraph Agent turn."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from workflowweave.agent.context.prompt import build_system_prompt
from workflowweave.agent.contracts import RuntimeIdentity
from workflowweave.agent.runtime.context import AgentContext
from workflowweave.agent.runtime.recovery import ensure_checkpoint_present, prepare_checkpoint
from workflowweave.agent.runtime.stream import (
    final_reasoning,
    runnable_config,
    stream_graph,
    tool_scope,
)
from workflowweave.ai.errors import ModelError, error_info
from workflowweave.ai.prompts import build_messages
from workflowweave.errors import WorkFLowWeaveError


@asynccontextmanager
async def _null_context(value=None):
    yield value


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
    return ""


def _last_text(result: dict[str, Any]) -> str:
    for message in reversed(result.get("messages", [])):
        if isinstance(message, AIMessage):
            return _content_text(message.content)
    raise WorkFLowWeaveError("invalid_response", "Agent 没有返回文本消息")


async def _has_published_delta(log, turn_id: str) -> bool:
    # Replay includes writes completed while cancellation was being propagated.
    return any(event["type"] == "message.delta" and event.get("turn_id") == turn_id
               for event in await log.replay())


class TurnRunner:
    def __init__(self, *, repository, turns, checkpoints, resource_provider,
                 model_provider, workspace, scheduler, artifacts,
                 sandbox_factory, collection_context_factory):
        self.repository = repository
        self.turns = turns
        self.checkpoints = checkpoints
        self.resource_provider = resource_provider
        self.model_provider = model_provider
        self.workspace = workspace
        self.scheduler = scheduler
        self.artifacts = artifacts
        self.sandbox_factory = sandbox_factory
        self.collection_context_factory = collection_context_factory
        from workflowweave.agent.runtime.builder import GraphBuilder
        self.graph_builder = GraphBuilder()
        self.graph = None

    async def run(self, session, turn_id: str, text: str, ready: asyncio.Event,
                  *, compact_only: bool = False) -> dict[str, Any]:
        log = self.repository.log(session.session_id)
        previous = any(event["type"].startswith("turn.") for event in log.events)
        context = None
        resources = None
        try:
            resources = self.resource_provider.capture(session)
            ready.set()
            config = resources.config
            await self.scheduler.resize(config.read_concurrency)
            message_id = "message_" + turn_id
            if not compact_only:
                await log.append("message.user", turn_id=turn_id, text=text, message_id=message_id)
            await log.append("turn.started", turn_id=turn_id, branch_id=session.branch_id)
            await log.append("turn.resources", turn_id=turn_id, model=resources.model,
                             tools_generation=resources.tools_generation)
            session.status = "running"
            session.turn_id = turn_id
            session.updated_at = log.events[-1]["created_at"]
            await self.repository.persist(session)
            identity = RuntimeIdentity(
                session.session_id, turn_id, session.branch_id,
                workflow_session_id=session.workflow_session_id, model=resources.model,
                tools_generation=resources.tools_generation, workspace=str(self.workspace.root),
            )
            view = self.workspace.for_identity(identity)
            if resources.gateway is not None:
                await resources.gateway.catalog(view, revision=turn_id)
            instructions = await view.instructions()
            prompt = build_system_prompt(
                agents=instructions, session_id=session.session_id, branch_id=session.branch_id,
                turn_id=turn_id, workspace=str(view.root),
                workflow_session_id=session.workflow_session_id,
                now=datetime.now(ZoneInfo(config.timezone)),
            )
            if session.system_prompt:
                prompt += "\n\n" + session.system_prompt
            context = AgentContext(
                workspace=view, sandbox=self.sandbox_factory(view), gateway=resources.gateway,
                config=config, session_id=session.session_id, turn_id=turn_id,
                branch_id=session.branch_id, event_log=log, scheduler=self.scheduler,
                artifacts=self.artifacts,
                read_enabled=any(item.name == "read" for item in resources.declarations),
                on_boundary=lambda **kwargs: self.turns._take_commands(session, **kwargs),
                collection=(self.collection_context_factory(session)
                            if self.collection_context_factory else None),
            )
            context.scope.allowed_tool_names = frozenset(item.name for item in resources.declarations)
            messages = []
            if not compact_only and session.workflow_input is not None and not any(
                event["type"] == "workflow.input.used" for event in log.events
            ):
                if session.workflow_task_id is not None:
                    input_text = (session.workflow_input if isinstance(session.workflow_input, str)
                                  else json.dumps(session.workflow_input, ensure_ascii=False, sort_keys=True))
                    messages.append(build_messages("", session.input_prompt, input_text)[1])
                else:
                    messages.append(HumanMessage(content=json.dumps(
                        {"input": session.workflow_input}, ensure_ascii=False, sort_keys=True)))
                await log.append("workflow.input.used", turn_id=turn_id)
            if not compact_only:
                messages.append(HumanMessage(content=text, id=message_id))
            await ensure_checkpoint_present(
                self.checkpoints.saver, session.session_id, require_existing=previous,
            )
            timeout = getattr(resources.ai_config, "timeout", None)
            timeout_context = asyncio.timeout(timeout) if timeout is not None else _null_context()
            async with timeout_context:
                async with self.model_provider.lease(
                    session, ai_config=resources.ai_config, model=resources.model,
                    output_tokens=config.output_tokens,
                ) as model:
                    separate_summary = (
                        resources.summary_ai_config is not None
                        or config.summary_max_tokens != config.output_tokens
                    )
                    if separate_summary and not self.model_provider.model_provider:
                        summary_context = self.model_provider.lease(
                            session,
                            ai_config=resources.summary_ai_config or resources.ai_config,
                            model=resources.summary_model or resources.model,
                            output_tokens=config.summary_max_tokens,
                        )
                    else:
                        summary_context = _null_context(model)
                    async with summary_context as summary_model, tool_scope(context):
                        context.scope.model = model
                        context.scope.system_prompt = prompt
                        context.scope.summary_model = summary_model
                        context.scope.summary_timeout = (
                            getattr(resources.summary_ai_config, "timeout", None)
                            if resources.summary_ai_config is not None else None
                        )
                        graph = self.graph_builder.bind(
                            context=context, generation=resources.tools_generation,
                        )
                        await prepare_checkpoint(
                            graph, lambda: self.checkpoints.projection,
                            session.session_id, log, turn_id, require_existing=previous,
                        )
                        graph_config = runnable_config(
                            session_id=session.session_id, turn_id=turn_id,
                            branch_id=session.branch_id,
                        )
                        if compact_only:
                            state = await graph.aget_state(graph_config)
                            update = await context.context_middleware.prepare(
                                state.values.get("messages", []), Runtime(context=context), force=True,
                            )
                            if update or not state.config.get("configurable", {}).get("checkpoint_id"):
                                await self.checkpoints.projection.aupdate_state(
                                    graph_config, update or {"messages": []}, as_node="projection",
                                )
                            await log.append("command.completed", command="compact",
                                             turn_id=turn_id, compacted=update is not None)
                            result = {"messages": []}
                        else:
                            result = await stream_graph(
                                graph, messages, context=context, config=graph_config, log=log,
                                idle_timeout=config.idle_timeout,
                            )
                        state = await graph.aget_state(graph_config)
                        checkpoint_id = state.config.get("configurable", {}).get("checkpoint_id")
            answer = "" if compact_only else _last_text(result)
            final_message = next((message for message in reversed(result.get("messages", []))
                                  if isinstance(message, AIMessage)), None)
            deltas = [event for event in log.events
                      if event["type"] == "message.delta" and event.get("turn_id") == turn_id
                      and (final_message is None or not final_message.id
                           or event.get("message_id") == final_message.id)]
            incremental = any(_content_text(event.get("content")) for event in deltas)
            completed = {"turn_id": turn_id, "incremental": incremental}
            if final_message is not None:
                completed["message_id"] = final_message.id
            if not incremental:
                completed["text"] = answer
            if not any(event.get("reasoning") for event in deltas):
                reasoning = final_reasoning(result) if not compact_only else ""
                if reasoning:
                    completed["reasoning"] = reasoning
            if not compact_only:
                await log.append("message.completed", **completed)
            await self.turns._cancel_pending_commands(session)
            await log.append("turn.completed", turn_id=turn_id, text=answer,
                             checkpoint_id=checkpoint_id,
                             command="compact" if compact_only else None)
            session.status = "completed"
            return {"turn_id": turn_id, "status": "completed", "text": answer}
        except asyncio.CancelledError:
            await self.turns._cancel_pending_commands(session)
            await log.append("turn.cancelled", turn_id=turn_id,
                             partial=await _has_published_delta(log, turn_id))
            session.status = "cancelled"
            raise
        except TimeoutError as exc:
            await self.turns._cancel_pending_commands(session)
            await log.append("turn.failed", turn_id=turn_id,
                             error={"code": "ai_timeout", "message": "模型调用总时限已耗尽"},
                             partial=await _has_published_delta(log, turn_id))
            session.status = "failed"
            raise WorkFLowWeaveError("ai_timeout", "模型调用总时限已耗尽",
                                {"timeout": getattr(resources.ai_config, "timeout", None)}) from exc
        except Exception as exc:
            await self.turns._cancel_pending_commands(session)
            error = (exc.info.model_dump(mode="json") if isinstance(exc, WorkFLowWeaveError)
                     else (exc.report or error_info(exc)).model_dump(mode="json")
                     if isinstance(exc, ModelError)
                     else {"type": type(exc).__name__, "message": str(exc)})
            await log.append("turn.failed", turn_id=turn_id, error=error,
                             partial=await _has_published_delta(log, turn_id))
            session.status = "failed"
            raise
        finally:
            ready.set()
            session.updated_at = log.events[-1]["created_at"]
            await self.repository.persist(session)
