"""Invocation budget shared with built-in adapters without changing plugin send()."""

import asyncio
from contextvars import ContextVar

delivery_deadline: ContextVar[float | None] = ContextVar("delivery_deadline", default=None)


def remaining_delivery_time(default: float) -> float:
    deadline = delivery_deadline.get()
    if deadline is None:
        return default
    return max(0.0, deadline - asyncio.get_running_loop().time())
