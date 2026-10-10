"""corespeed WeChatBot SDK channel plugin entry point."""

from __future__ import annotations

from .channel import WechatOpenClawChannelType


class Plugin:
    def register(self, api) -> None:
        api.register_channel(WechatOpenClawChannelType())


plugin = Plugin()
