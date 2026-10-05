from .collector import LogsCollector


class Plugin:
    def register(self, api):
        api.register_collector(LogsCollector())


plugin = Plugin()
