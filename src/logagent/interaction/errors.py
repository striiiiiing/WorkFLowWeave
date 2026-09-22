"""Stable HTTP projection for structured application errors."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from logagent.errors import LogAgentError
from logagent.models import ErrorInfo, ErrorResponse

logger = logging.getLogger("logagent.interaction")

_VALIDATION_CODES = {
    "invalid_argument",
    "invalid_config",
    "invalid_declaration",
    "invalid_reference",
    "invalid_schema",
    "capability_missing",
    "validation",
    "context_budget_unavailable",
}
_CONFLICT_CODES = {
    "already_exists",
    "checkpoint_missing",
    "not_found",
    "plugin_reload_conflict",
    "recovery_unavailable",
    "reference_conflict",
    "session_active",
    "session_exists",
    "session_not_found",
    "session_not_active",
    "version_not_found",
    "workflow_disabled",
    "workflow_no_enabled_sources",
    "request_conflict",
    "session_busy",
    "tool_key_conflict",
    "model_ambiguous",
    "compact_conflict",
    "agent_busy",
}
_UNAVAILABLE_CODES = {
    "checkpoint",
    "checkpoint_unavailable",
    "configuration_unavailable",
    "lifecycle_shutdown_failed",
    "lifecycle_start_failed",
    "not_ready",
    "shutdown",
    "storage",
    "storage_closed",
    "storage_failed",
}


def status_for_code(code: str) -> int:
    if code in _VALIDATION_CODES:
        return 422
    if code in _CONFLICT_CODES:
        return 409
    if code == "capacity" or code.startswith("capacity_"):
        return 429
    if code in _UNAVAILABLE_CODES or code.startswith(("storage_", "checkpoint_")):
        return 503
    return 500


def error_response(status_code: int, info: ErrorInfo) -> JSONResponse:
    body = ErrorResponse(error=info)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


async def logagent_error_handler(_: Request, exc: LogAgentError) -> JSONResponse:
    return error_response(status_for_code(exc.code), exc.info)


async def request_validation_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "path": list(issue["loc"]),
            "reason": issue["type"],
        }
        for issue in exc.errors()
    ]
    return error_response(
        422,
        ErrorInfo(
            code="validation",
            message="请求参数或资源结构不符合契约",
            details={"errors": errors},
        ),
    )


async def pydantic_error_handler(_: Request, exc: ValidationError) -> JSONResponse:
    errors = [
        {
            "path": list(issue["loc"]),
            "reason": issue["type"],
        }
        for issue in exc.errors(
            include_input=False,
            include_context=False,
            include_url=False,
        )
    ]
    return error_response(
        422,
        ErrorInfo(
            code="validation",
            message="请求参数或资源结构不符合契约",
            details={"errors": errors},
        ),
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_interaction_error",
        extra={"event": "unhandled_interaction_error"},
    )
    return error_response(
        500,
        ErrorInfo(
            code="internal_error",
            message="服务内部错误",
            details={},
        ),
    )
