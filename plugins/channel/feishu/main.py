"""Feishu channel plugin entry point.

The SDK is intentionally imported by the channel instance, rather than when
the plugin is discovered.  A missing optional SDK therefore only disables this
channel and does not hide the remaining plugin set.
"""

from __future__ import annotations

from .channel import FeishuChannelType


class Plugin:
    def register(self, api) -> None:
        api.register_channel(FeishuChannelType())


plugin = Plugin()
