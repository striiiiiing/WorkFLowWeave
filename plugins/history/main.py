from .collector import HistoryCollector


class Plugin:
    def register(self, api):
        api.register_collector(HistoryCollector())


plugin = Plugin()
