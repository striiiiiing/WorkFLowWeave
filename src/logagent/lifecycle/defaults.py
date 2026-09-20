"""Local starter resources, used only when creating a new resource document."""

from logagent.models import ChannelConfig, ResourceKind, SourceConfig, StrictModel


def starter_resources() -> dict[ResourceKind, list[StrictModel]]:
    return {
        "sources": [
            SourceConfig(id="default_mock", collector="mock"),
            SourceConfig(id="default_history", collector="history"),
            SourceConfig(id="default_logs", collector="logs"),
        ],
        "channels": [
            ChannelConfig(
                id="default_file", channel="mock", options={"path": "notifications.txt"}
            ),
        ],
    }
