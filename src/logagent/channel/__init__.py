from .errors import ChannelDeliveryError
from .manager import ChannelManager
from .unified_queue import QueueOutcome, UnifiedQueue
from .web import WebChannel, WebChannelType

__all__ = [
    "builtin_channels",
    "ChannelDeliveryError",
    "ChannelManager",
    "QueueOutcome",
    "UnifiedQueue",
    "WebChannel",
    "WebChannelType",
]


def builtin_channels():
    """Default declarations injected by application assembly; no network I/O."""
    return [WebChannelType()]
