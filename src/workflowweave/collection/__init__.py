"""MCP/CLI collection runtime."""
from workflowweave.collection.files import FileReferenceStore
from workflowweave.collection.manager import CollectorManager

__all__ = [
    "CollectorManager",
    "FileReferenceStore",
]
