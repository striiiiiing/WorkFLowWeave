"""Channel-reported delivery failures.

Adapters raise this to state the outcome they actually observed. Leaving
`uncertain` False asserts the message was definitively not accepted; setting
it True marks a possibly accepted message whose acknowledgement was lost.
"""

from __future__ import annotations

from typing import Any

from workflowweave.errors import WorkFLowWeaveError


class ChannelDeliveryError(WorkFLowWeaveError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        uncertain: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, details)
        self.uncertain = uncertain
