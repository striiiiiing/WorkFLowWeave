"""Agent storage name for cancellation-owned blocking file operations."""

from workflowweave.storage_primitives.locks import run_blocking_owned

file_io = run_blocking_owned

__all__ = ["file_io"]
