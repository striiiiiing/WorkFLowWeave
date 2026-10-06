"""Local duplex channel used only by tests."""

from copy import deepcopy

from workflowweave.channel.conversation import ChannelAddress, InboundHandler, InboundMessage
from workflowweave.channel.errors import ChannelDeliveryError
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import ChannelConfig, Notification


class TestChannel:
    __test__ = False

    def __init__(self, config: ChannelConfig):
        self.target = config.options.get("target", "local")
        self.handler: InboundHandler | None = None
        self.messages: list[dict] = []
        self.started = False

    async def start(self):
        self.started = True

    async def start_receiving(self, handler: InboundHandler):
        self.handler = handler

    async def stop_receiving(self):
        self.handler = None

    async def inject(self, message: InboundMessage) -> dict:
        if self.handler is None:
            raise WorkFLowWeaveError("channel_disabled", "测试渠道未启用 Agent 接收")
        return await self.handler(InboundMessage.model_validate(message).model_copy(deep=True))

    async def send(self, notification: Notification, *, options: dict):
        self._record(notification, {"kind": "test", "target": self.target}, options)

    async def reply(self, notification: Notification, *, address: ChannelAddress, options: dict):
        self._record(notification, address.model_dump(), options)

    def _record(self, notification, address, options):
        if not self.started:
            raise ChannelDeliveryError("channel_closed", "测试渠道已关闭")
        if options:
            raise ChannelDeliveryError("invalid_config", "测试渠道没有调用选项")
        self.messages.append(
            {
                "id": len(self.messages) + 1,
                "address": deepcopy(address),
                "notification": notification.model_dump(mode="json"),
                "request_id": notification.metadata.get("request_id"),
                "session_id": notification.session_id,
                "turn_id": notification.metadata.get("turn_id"),
                "status": "success",
            }
        )

    def outbox(self, *, after: int = 0):
        return deepcopy(self.messages[after:])

    def receiver_status(self):
        return {"state": "running" if self.handler is not None else "stopped", "error": None}

    async def stop(self):
        await self.stop_receiving()
        self.started = False


class TestChannelType:
    __test__ = False
    name = "test"
    id_prefix = "test"
    description = "Local duplex test channel"
    capabilities = ["notification", "conversation"]
    options_schema = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "minLength": 1,
                "default": "local",
                "description": "Single direction test target",
            }
        },
        "additionalProperties": False,
    }

    async def create(self, config: ChannelConfig, credentials):
        del credentials
        return TestChannel(config)
