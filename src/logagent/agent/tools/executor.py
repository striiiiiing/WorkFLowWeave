"""The only tool scheduling, side-effect reservation and result commit path."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from time import monotonic
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.messages.utils import count_tokens_approximately

from logagent.errors import LogAgentError
from logagent.redaction import redact_data, redact_text


def _tool_error(error: LogAgentError) -> dict[str, Any]:
    return {"status": "failed", "error": error.info.model_dump(mode="json")}


async def execute_tool(declaration, arguments, context, *, tool_call_id: str):
    key = f"{context.session_id}:{context.turn_id}:{tool_call_id}"
    existing = context.scope.tasks.get(key)
    if existing is not None:
        return await asyncio.shield(existing)

    async def execute():
        started = False
        began = monotonic()
        metadata = {"turn_id": context.turn_id, "tool_call_id": tool_call_id,
                    "name": declaration.name, "arguments": redact_data(arguments)}
        try:
            execution = (context.gateway.execution(arguments)
                         if declaration.name == "mcp" and context.gateway is not None
                         else declaration.execution)
            metadata["execution"] = execution
            await context.event_log.append("tool.queued", tool_key=key, **metadata)
            async with context.scheduler.acquire(execution):
                reservation = await context.event_log.reserve_tool(key, arguments, **metadata)
                if reservation.status in {"tool.completed", "tool.outcome_unknown"}:
                    return reservation.result or {}
                if reservation.status == "active":
                    completed = await context.event_log.wait_for_tool(key, arguments)
                    return completed.result or {}
                started = True
                try:
                    result = await declaration.invoke(arguments, replace(context, tool_call_id=key))
                except Exception as error:
                    result = (_tool_error(error) if isinstance(error, LogAgentError) else
                              {"status": "failed", "error": {"code": "tool_failed",
                               "message": redact_text(str(error)), "type": type(error).__name__}})
                    if not isinstance(error, LogAgentError):
                        await context.event_log.complete_tool(key, arguments, result)
                        raise
                if not isinstance(result, dict):
                    result = {"status": "success", "value": result}
                if context.artifacts is not None:
                    result = await context.artifacts.save(
                        result, session_id=context.session_id, turn_id=context.turn_id,
                        tool_call_id=tool_call_id, config=context.config,
                        count_tokens=lambda text: count_tokens_approximately(
                            [HumanMessage(content=text)]
                        ),
                        schema_output=declaration.name == "mcp" and arguments.get("action") == "describe",
                        read_enabled=context.read_enabled,
                        preserve_full=declaration.name == "mcp",
                    )
                result["duration_ms"] = round((monotonic() - began) * 1000)
                await context.event_log.complete_tool(key, arguments, result)
                return result
        except asyncio.CancelledError:
            if started:
                await context.event_log.mark_unknown(key, arguments, reason="cancelled")
            else:
                await context.event_log.append(
                    "tool.completed", tool_key=key, result={"status": "cancelled"}, **metadata,
                )
            raise
        except LogAgentError as error:
            if error.code in {"event_log_corrupt", "tool_key_conflict"}:
                raise
            result = _tool_error(error)
            if started:
                await context.event_log.complete_tool(key, arguments, result)
            else:
                await context.event_log.append("tool.completed", tool_key=key, result=result, **metadata)
            return result

    task = asyncio.create_task(execute(), name=f"agent:tool:{declaration.name}")
    context.scope.tasks[key] = task
    try:
        return await asyncio.shield(task)
    finally:
        if task.done():
            context.scope.tasks.pop(key, None)
