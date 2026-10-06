"""Local starter resources, used only when creating a new resource document."""

from workflowweave.models import ResourceKind, StrictModel


def starter_resources() -> dict[ResourceKind, list[StrictModel]]:
    return {}
