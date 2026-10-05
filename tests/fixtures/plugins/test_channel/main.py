from tests.fixtures.channels import TestChannelType


class Plugin:
    def register(self, api):
        api.register_channel(TestChannelType())


plugin = Plugin()
