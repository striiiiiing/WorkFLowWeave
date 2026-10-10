"""Python adapter contract tests for the Node SDK bridge boundary."""

import asyncio
import json

import pytest

from workflowweave.models import ChannelConfig, Notification
from workflowweave.plugins.channel.wechat_openclaw.channel import (
    WechatOpenClawChannel,
    WechatOpenClawChannelType,
)


class BridgeProcess:
    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdin = self
        self.returncode = None
        self.requests = []
        self.finished = asyncio.Event()
        self.emit({"type": "ready", "protocol_version": 1, "account_id": "account"})

    def emit(self, event):
        self.stdout.feed_data((json.dumps(event) + "\n").encode())

    def write(self, raw):
        event = json.loads(raw)
        self.requests.append(event)
        if event["type"] != "inbound_ack":
            self.emit({"type": "ack", "request_id": event["request_id"],
                       "status": "sent" if event["type"] == "send" else "accepted"})

    async def drain(self):
        return None

    def close(self):
        self.returncode = 0
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.finished.set()

    async def wait(self):
        await self.finished.wait()
        return self.returncode


@pytest.mark.asyncio
async def test_ipc_handshake_send_receive_and_stop():
    process = BridgeProcess()

    async def factory(*args, **kwargs):
        return process

    channel = WechatOpenClawChannel(ChannelConfig(
        id="wx", channel="wechat_openclaw",
        options={"account_id": "account", "target_id": "peer"},
    ), process_factory=factory)
    received = asyncio.Event()

    async def receive(message):
        assert message.text == "hello"
        received.set()
        return {"status": "accepted"}

    await channel.start()
    await channel.send(Notification(session_id="s", output_id="o", text="notice"), options={})
    await channel.start_receiving(receive)
    process.emit({"type": "message", "message_id": "m", "text": "hello",
                  "conversation_kind": "weixin", "conversation_id": "peer", "sender_id": "peer"})
    await asyncio.wait_for(received.wait(), 1)
    assert process.requests[-1]["type"] == "inbound_ack"
    await channel.stop_receiving()
    await channel.stop()


def test_schema_describes_web_login_and_hard_context_limit():
    assert WechatOpenClawChannelType.capabilities == ["notification", "conversation"]
    assert "context_token" in WechatOpenClawChannelType.description
    assert "不建议作为单向通知渠道" in WechatOpenClawChannelType.description
    assert "account_id" in WechatOpenClawChannelType.options_schema["properties"]
    assert "不建议将微信作为单向通知渠道" in WechatOpenClawChannelType.options_schema["properties"]["target_id"]["description"]
