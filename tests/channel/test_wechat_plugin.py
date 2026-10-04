"""使用本地 IPC 进程替身验证微信 ready、接收、回复、停收和显式登录失败。"""

import asyncio
import json

import pytest

from logagent.channel.errors import ChannelDeliveryError
from logagent.models import ChannelConfig, Notification
from plugins.channel.wechat_openclaw.channel import WechatOpenClawChannel


class BridgeProcess:
    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdin = self
        self.returncode = None
        self.requests = []
        self.finished = asyncio.Event()
        self.reject_send = False
        self.emit({"type": "ready", "protocol_version": 1, "account_id": "account"})

    def emit(self, event):
        self.stdout.feed_data((json.dumps(event) + "\n").encode())

    def write(self, raw):
        event = json.loads(raw)
        self.requests.append(event)
        if event["type"] == "inbound_ack":
            return
        rejected = self.reject_send and event["type"] == "send"
        self.emit({"type": "error" if rejected else "ack", "request_id": event["request_id"],
                   "status": "sent" if event["type"] == "send" else "accepted",
                   "code": "weixin_send_failed", "uncertain": rejected})

    async def drain(self):
        pass

    def close(self):
        self.returncode = 0
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.finished.set()

    async def wait(self):
        await self.finished.wait()
        return self.returncode


@pytest.mark.asyncio
async def test_bridge_handshake_single_send_inbound_reply_and_resume():
    process = BridgeProcess()
    launches = []

    async def factory(*args, **kwargs):
        launches.append((args, kwargs))
        return process

    channel = WechatOpenClawChannel(ChannelConfig(
        id="wx", channel="wechat_openclaw", options={"account_id": "account", "target_id": "peer"},
    ), process_factory=factory)
    seen = []
    admitted = asyncio.Event()

    async def receive(message):
        seen.append(message)
        admitted.set()
        return {"status": "accepted"}

    await channel.start()
    assert "--account-id" in launches[0][0]
    notification = Notification(session_id="s", output_id="o", text="notice")
    await channel.send(notification, options={})
    assert process.requests[-1]["route"] == {"kind": "weixin", "target": "peer"}
    assert not any(value["type"] == "start_receiving" for value in process.requests)
    await channel.start_receiving(receive)
    process.emit({"type": "message", "message_id": "m", "text": "hello", "conversation_kind": "weixin",
                  "conversation_id": "peer", "sender_id": "peer"})
    await asyncio.wait_for(admitted.wait(), 1)
    await asyncio.sleep(0)
    assert process.requests[-1]["type"] == "inbound_ack"
    await channel.reply(notification, address=seen[0].address, options={})
    await channel.stop_receiving()
    await channel.start_receiving(receive)
    process.reject_send = True
    with pytest.raises(ChannelDeliveryError) as error:
        await channel.send(notification, options={})
    assert error.value.uncertain
    await channel.stop()
    assert process.returncode == 0


@pytest.mark.asyncio
async def test_missing_ready_fails_start_explicitly():
    async def factory(*args, **kwargs):
        process = BridgeProcess()
        process.stdout = asyncio.StreamReader()
        process.emit({"type": "fatal", "code": "weixin_login_required"})
        return process

    channel = WechatOpenClawChannel(ChannelConfig(
        id="wx", channel="wechat_openclaw", options={"account_id": "account"},
    ), process_factory=factory)
    with pytest.raises(ChannelDeliveryError) as error:
        await channel.start()
    assert error.value.details["code"] == "weixin_login_required"
    await channel.stop()


@pytest.mark.asyncio
async def test_send_pipe_drain_failure_after_write_is_uncertain():
    process = BridgeProcess()

    async def factory(*args, **kwargs):
        return process

    channel = WechatOpenClawChannel(ChannelConfig(
        id="wx", channel="wechat_openclaw", options={"account_id": "account", "target_id": "peer"},
    ), process_factory=factory)
    await channel.start()

    async def broken_drain():
        raise BrokenPipeError("private pipe detail")

    process.drain = broken_drain
    try:
        with pytest.raises(ChannelDeliveryError) as error:
            await channel.send(Notification(session_id="s", output_id="o", text="notice"), options={})
        assert error.value.uncertain
        assert "private" not in str(error.value.details)
    finally:
        await channel.stop()
