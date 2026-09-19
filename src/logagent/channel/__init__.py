from .email import EmailChannel, EmailChannelType
from .errors import ChannelDeliveryError
from .manager import ChannelManager
from .mock import MockFileChannel, MockFileChannelType

__all__ = [
    "EmailChannel",
    "EmailChannelType",
    "builtin_channels",
    "ChannelDeliveryError",
    "ChannelManager",
    "MockFileChannel",
    "MockFileChannelType",
]


def builtin_channels():
    """Default declarations injected by application assembly; no network I/O."""
    return [MockFileChannelType(), EmailChannelType()]
