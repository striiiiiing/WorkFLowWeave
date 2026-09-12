"""Errors safe to expose at application boundaries."""

from typing import Any


class LogAgentError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}

    def to_info(self):
        from logagent.models import ErrorInfo

        return ErrorInfo(**self.as_dict())
