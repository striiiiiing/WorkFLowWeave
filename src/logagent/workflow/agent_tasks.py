"""Adapt one owned Agent turn to a frozen Workflow task result."""

from __future__ import annotations

import asyncio

from logagent.ai.errors import ModelError, error_info
from logagent.errors import LogAgentError, exception_error
from logagent.models import AnalysisResult, ErrorInfo

_TIMEOUT_CODES = {"ai_timeout", "model_idle_timeout", "provider_timeout"}


async def execute_agent_task(
    service,
    *,
    operation_id,
    workflow_session_id,
    workflow_task_id,
    ai_config,
    model,
    workflow_result,
    system_prompt="",
    input_prompt="{input}",
    user_prompt,
    tool_names,
    mcp_binding=None,
):
    """Wait for the first turn; subsequent conversation never changes its result.

    The service owns operation and request deduplication, including after restart.
    Admission remains owned during cancellation so an accepted tool turn cannot
    outlive its parent Workflow merely because cancellation arrived twice.
    """
    session_id = None
    admission = asyncio.create_task(service.create_session(
        model=model,
        workflow_session_id=workflow_session_id,
        workflow_task_id=workflow_task_id,
        ai_config=ai_config,
        workflow_result=workflow_result,
        system_prompt=system_prompt,
        input_prompt=input_prompt,
        user_prompt=user_prompt,
        tool_names=tool_names,
        operation_id=operation_id,
        mcp_binding=mcp_binding,
    ))
    try:
        session = await asyncio.shield(admission)
        session_id = session["session_id"]
        admission = asyncio.create_task(service.submit(
            session_id, user_prompt, request_id=operation_id,
        ))
        accepted = await asyncio.shield(admission)
        outcome = await service.wait(accepted["turn_id"])
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError
        if outcome["status"] == "completed":
            return AnalysisResult(
                task_id=workflow_task_id, status="success", text=outcome["text"],
                agent_session_id=session_id,
            )
        error = outcome.get("error")
        info = (ErrorInfo.model_validate(error) if error and error.get("code") else
                ErrorInfo(code="agent_" + outcome["status"], message="Agent 任务未完成",
                          details=error or {}))
        status = "cancelled" if outcome["status"] == "cancelled" else "failed"
        return _failed_result(workflow_task_id, session_id, info, status=status)
    except asyncio.CancelledError:
        cleanup = asyncio.create_task(_cancel_admitted(service, admission, session_id))
        session_id, cancelled = await _settle_cleanup(cleanup)
        if cancelled:
            raise asyncio.CancelledError from None
        return _failed_result(
            workflow_task_id, session_id,
            ErrorInfo(code="agent_cancelled", message="Agent 任务已取消"), status="cancelled",
        )
    except LogAgentError as exc:
        return _failed_result(workflow_task_id, session_id, exc.info)
    except ModelError as exc:
        return _failed_result(workflow_task_id, session_id, exc.report or error_info(exc))
    except Exception as exc:
        return _failed_result(
            workflow_task_id, session_id,
            exception_error(exc, code="agent_failed", message="Agent 任务执行失败"),
        )


def _failed_result(task_id, session_id, error, *, status="failed"):
    if status == "failed" and error.code in _TIMEOUT_CODES:
        status = "timeout"
    return AnalysisResult(
        task_id=task_id, status=status, agent_session_id=session_id, error=error,
    )


async def _cancel_admitted(service, admission, session_id):
    try:
        accepted = await admission
    finally:
        # A rejected submit still leaves an already-created session to settle.
        if session_id is not None:
            await service.cancel(session_id)
    if session_id is None:
        session_id = accepted["session_id"]
        await service.cancel(session_id)
    return session_id


async def _settle_cleanup(cleanup):
    cancelled = bool(asyncio.current_task().cancelling())
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled |= bool(asyncio.current_task().cancelling())
    return cleanup.result(), cancelled
