"""Local starter resources, used only when creating a new resource document."""

from logagent.models import ChannelConfig, ResourceKind, StrictModel


def starter_resources() -> dict[ResourceKind, list[StrictModel]]:
    return {
        "sources": [],
        "channels": [
            ChannelConfig(
                id="default_file", channel="mock", options={"path": "notifications.txt"}
            ),
        ],
    }
