from .channel import QQChannelType


class Plugin:
    def register(self, api):
        api.register_channel(QQChannelType())


plugin = Plugin()
