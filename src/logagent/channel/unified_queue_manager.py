"""Compatibility name for the Manager-owned keyed input queue."""

from .unified_queue import QueueOutcome, UnifiedQueue

UnifiedQueueManager = UnifiedQueue

__all__ = ["QueueOutcome", "UnifiedQueue", "UnifiedQueueManager"]

