"""Single-source asynchronous collection and its three built-in capabilities."""

from logagent.collection.logs import LogsCollector
from logagent.collection.manager import CollectorManager
from logagent.protocols import Collector

__all__ = [
    "CollectorManager",
    "LogsCollector",
    "builtin_collectors",
]


def builtin_collectors() -> tuple[Collector, ...]:
    """Fresh implementations for configuration's built-in registration phase."""
    return (LogsCollector(),)
