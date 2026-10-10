from .channel import FileChannelType


class Plugin:
    def register(self, api):
        api.register_channel(FileChannelType())


plugin = Plugin()
