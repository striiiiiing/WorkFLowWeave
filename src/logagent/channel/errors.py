"""Channel-reported delivery failures.

Adapters raise this to state the outcome they actually observed. Leaving
`uncertain` False asserts the message was definitively not accepted; setting
it True marks a possibly accepted message whose acknowledgement was lost.
"""

from __future__ import annotations

from typing import Any

from logagent.errors import LogAgentError


class ChannelDeliveryError(LogAgentError):
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
