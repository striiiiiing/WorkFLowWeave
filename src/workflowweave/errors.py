"""Public, structured errors without arbitrary exception text or input dumps."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from workflowweave.models import ErrorInfo


class WorkFLowWeaveError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        self.info = ErrorInfo(code=code, message=message, details=details or {})
        super().__init__(message)

    @property
    def code(self) -> str:
        return self.info.code

    @property
    def details(self) -> dict[str, Any]:
        return self.info.details


def validation_error(exc: ValidationError, *, code: str = "invalid_config") -> WorkFLowWeaveError:
    return WorkFLowWeaveError(
        code,
        "配置或返回结构不符合契约",
        {
            "errors": [
                {"path": list(issue["loc"]), "reason": issue["type"]}
                for issue in exc.errors(
                    include_input=False, include_context=False, include_url=False
                )
            ]
        },
    )


def exception_error(
    exc: Exception, *, code: str, message: str, details: dict[str, Any] | None = None
) -> ErrorInfo:
    """Exception messages can contain credentials, input, or host paths."""
    return ErrorInfo(
        code=code,
        message=message,
        details={**(details or {}), "exception_type": type(exc).__name__},
    )
