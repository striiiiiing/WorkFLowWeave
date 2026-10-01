"""FastAPI and thin CLI boundary for LogAgent."""

from .schemas import CancelResponse, ReloadResponse, TriggerRequest, TriggerResponse

__all__ = [
    "CancelResponse",
    "ReloadResponse",
    "TriggerRequest",
    "TriggerResponse",
    "create_app",
]


def __getattr__(name: str):
    """Load the FastAPI factory only for callers that explicitly request it."""
    if name == "create_app":
        from .app import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
