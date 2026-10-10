from .channel import TelegramChannelType


class Plugin:
    def register(self, api):
        api.register_channel(TelegramChannelType())


plugin = Plugin()
