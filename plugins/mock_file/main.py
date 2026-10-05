from .channel import MockFileChannelType


class Plugin:
    def register(self, api):
        api.register_channel(MockFileChannelType())


plugin = Plugin()
