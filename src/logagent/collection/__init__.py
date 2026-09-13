"""Single-source asynchronous collection and its three built-in capabilities."""

from logagent.collection.history import HistoryCollector
from logagent.collection.logs import LogsCollector
from logagent.collection.manager import CollectorManager
from logagent.collection.mock import MockCollector
from logagent.protocols import Collector

__all__ = [
    "CollectorManager",
    "HistoryCollector",
    "LogsCollector",
    "MockCollector",
    "builtin_collectors",
]


def builtin_collectors() -> tuple[Collector, ...]:
    """Fresh implementations for configuration's built-in registration phase."""
    return MockCollector(), LogsCollector(), HistoryCollector()
