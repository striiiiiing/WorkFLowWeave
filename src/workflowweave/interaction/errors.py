"""Stable HTTP projection for structured application errors."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import ErrorInfo, ErrorResponse

logger = logging.getLogger("workflowweave.interaction")

_VALIDATION_CODES = {
    "invalid_argument",
    "invalid_config",
    "invalid_declaration",
    "invalid_reference",
    "invalid_schema",
    "mcp_catalog_invalid",
    "capability_missing",
    "channel_not_conversation",
    "validation",
    "context_budget_unavailable",
}
_CONFLICT_CODES = {
    "channel_disabled",
    "channel_unbound",
    "channel_binding_changed",
    "request_outcome_unknown",
    "target_unavailable",
    "mcp_disabled",
    "mcp_out_of_scope",
    "mcp_tool_missing",
    "already_exists",
    "checkpoint_missing",
    "checkpoint_incompatible",
    "stage_unavailable",
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
    "file_conflict",
    "replace_conflict",
    "session_conflict",
    "session_busy",
    "tool_key_conflict",
    "model_ambiguous",
    "compact_conflict",
    "workflow_result_unavailable",
    "turn_not_found",
    "message_not_found",
    "agent_busy",
}
_UNAVAILABLE_CODES = {
    "channel_unavailable",
    "checkpoint",
    "checkpoint_unavailable",
    "configuration_unavailable",
    "mcp_cache_invalid",
    "mcp_directory_failed",
    "lifecycle_shutdown_failed",
    "lifecycle_start_failed",
    "not_ready",
    "shutdown",
    "storage",
    "storage_closed",
    "storage_failed",
}


def status_for_code(code: str) -> int:
    if code == "precondition_required":
        return 428
    if code in {"read_only", "path_forbidden", "session_forbidden"}:
        return 403
    if code in {"file_missing", "channel_not_found", "request_not_found"}:
        return 404
    if code in _VALIDATION_CODES:
        return 422
    if code in _CONFLICT_CODES:
        return 409
    if code == "capacity" or code.startswith("capacity_"):
        return 429
    if code == "channel_queue_full":
        return 429
    if code in _UNAVAILABLE_CODES or code.startswith(("storage_", "checkpoint_")):
        return 503
    return 500


def error_response(status_code: int, info: ErrorInfo) -> JSONResponse:
    body = ErrorResponse(error=info)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


async def workflowweave_error_handler(_: Request, exc: WorkFLowWeaveError) -> JSONResponse:
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
