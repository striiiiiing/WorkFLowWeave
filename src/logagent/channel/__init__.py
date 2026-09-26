from .email import EmailChannel, EmailChannelType
from .errors import ChannelDeliveryError
from .manager import ChannelManager
from .mock import MockFileChannel, MockFileChannelType
from .qq import QQChannelType
from .testing import TestChannelType
from .unified_queue import QueueOutcome, UnifiedQueue
from .web import WebChannel, WebChannelType

__all__ = [
    "EmailChannel",
    "EmailChannelType",
    "builtin_channels",
    "ChannelDeliveryError",
    "ChannelManager",
    "MockFileChannel",
    "MockFileChannelType",
    "QueueOutcome",
    "UnifiedQueue",
    "WebChannel",
    "WebChannelType",
]


def builtin_channels():
    """Default declarations injected by application assembly; no network I/O."""
    return [MockFileChannelType(), EmailChannelType(), QQChannelType(), TestChannelType(),
            WebChannelType()]
