from logagent.collection.mock import MockCollector


class Plugin:
    def register(self, api):
        api.register_collector(MockCollector())


plugin = Plugin()
