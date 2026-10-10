"""Transport contracts. Only the Agent runtime consumes inbound messages."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import Field

from workflowweave.models import JSONObject, Notification, StrictModel


class ChannelAddress(StrictModel):
    # Platform-specific route kinds are opaque to the shared manager.  The
    # concrete adapter validates and interprets them when sending a reply.
    kind: str = Field(min_length=1, pattern=r"^\S+$")
    target: str = Field(min_length=1, pattern=r"\S")
    sender: str = Field(min_length=1, pattern=r"\S")
    message_id: str = Field(min_length=1, pattern=r"\S")
    conversation_type: str | None = None

    @property
    def peer(self) -> tuple[str, str, str]:
        # Preserve each source's deduplication identity and trusted reply route.
        return self.kind, self.target, self.sender


class InboundMessage(StrictModel):
    request_id: str = Field(min_length=1, pattern=r"\S")
    text: str = Field(min_length=1, pattern=r"\S")
    address: ChannelAddress


InboundHandler = Callable[[InboundMessage], Awaitable[dict]]


class ConversationChannel(Protocol):
    async def start_receiving(self, handler: InboundHandler) -> None: ...

    async def stop_receiving(self) -> None: ...

    async def reply(
        self, notification: Notification, *, address: ChannelAddress, options: JSONObject,
    ) -> None: ...
