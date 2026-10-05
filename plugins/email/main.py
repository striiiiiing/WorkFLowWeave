from .channel import EmailChannelType


class Plugin:
    def register(self, api):
        api.register_channel(EmailChannelType())


plugin = Plugin()
