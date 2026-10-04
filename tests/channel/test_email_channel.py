"""邮件渠道的真实回环 SMTP 协议测试。

启动进程内 SMTP 服务，检查 MIME 正文、连接复用、账户与收件人隔离；
模拟认证拒绝、TLS、断连、超时和取消，核对明确失败/不确定回执且不自动重投。
另验配置校验与注入防护；协议走本地网络，不向外部邮箱发送邮件。
"""

import asyncio
from contextlib import asynccontextmanager
from email import policy
from email.parser import BytesParser

import pytest

from logagent.channel import ChannelManager
from logagent.channel.errors import ChannelDeliveryError
from logagent.config import PluginRegistry, ResourceStore
from logagent.errors import LogAgentError
from logagent.models import ChannelConfig, Notification, SystemConfig
from logagent.schema import validate_instance
from plugins.channel.email.channel import EmailChannel, EmailChannelType


class SMTPServer:
    def __init__(self, mode):
        self.mode = mode
        self.connections = 0
        self.messages = []
        self.commands = []
        self.tasks = set()
        self.writers = set()
        self.data_received = asyncio.Event()
        self.release = asyncio.Event()

    async def client(self, reader, writer):
        self.connections += 1
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.add(writer)
        try:
            writer.write(b"220 localhost test SMTP\r\n")
            await writer.drain()
            while raw := await reader.readline():
                command = raw.split(b" ", 1)[0].strip().upper()
                self.commands.append(command)
                if command in (b"EHLO", b"HELO"):
                    writer.write(b"250-localhost\r\n250 AUTH PLAIN\r\n")
                elif command == b"AUTH":
                    writer.write(b"535 test-private authentication refused\r\n")
                elif command == b"MAIL":
                    writer.write(b"250 sender accepted\r\n")
                elif command == b"RCPT":
                    writer.write(b"550 test-private rejected\r\n" if self.mode == "recipient" else b"250 recipient accepted\r\n")
                elif command == b"DATA":
                    writer.write(b"354 send content\r\n")
                    await writer.drain()
                    body = bytearray()
                    while (line := await reader.readline()) != b".\r\n":
                        if not line:
                            return
                        body.extend(line[1:] if line.startswith(b"..") else line)
                    self.messages.append(bytes(body))
                    self.data_received.set()
                    if self.mode == "drop":
                        return
                    if self.mode == "timeout":
                        await self.release.wait()
                        return
                    if self.mode == "hold":
                        await self.release.wait()
                    if self.mode == "reject":
                        writer.write(b"554 test-private rejected\r\n")
                    else:
                        writer.write(b"250 queued\r\n")
                        if self.mode == "accepted_drop":
                            await writer.drain()
                            return
                elif command == b"QUIT":
                    writer.write(b"221 bye\r\n")
                    await writer.drain()
                    return
                else:
                    writer.write(b"500 unsupported\r\n")
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            self.writers.discard(writer)
            self.tasks.discard(task)


@asynccontextmanager
async def smtp_server(mode="success"):
    smtp = SMTPServer(mode)
    server = await asyncio.start_server(smtp.client, "127.0.0.1", 0)
    smtp.port = server.sockets[0].getsockname()[1]
    try:
        yield smtp
    finally:
        server.close()
        smtp.release.set()
        for writer in tuple(smtp.writers):
            writer.close()
        await asyncio.gather(*smtp.tasks)
        await server.wait_closed()


def options(port=2525, **changes):
    return {"host": "127.0.0.1", "port": port, "sender": "from@example.test",
            "recipient": "to@example.test", "tls": "none", **changes}


def config(port, timeout=1, **changes):
    return ChannelConfig(id="mail", channel="email", options=options(port, **changes), timeout=timeout)


def note(text="第一行\n第二行", title="日报", output_id="output"):
    return Notification(session_id="session", output_id=output_id, title=title, text=text,
                        metadata={"recipient": "must-not-be-used@example.test"})


class Register:
    plugin = EmailChannelType()
    def get(self, name):
        return self.plugin if name == "email" else None
    def describe(self):
        return []


@pytest.mark.parametrize("changes", [
    {"port": 0}, {"port": 65536}, {"host": " "}, {"host": "host\r\nMAIL"},
    {"sender": "x@example.test\nBcc: y@example.test"},
    {"recipient": "x@example.test,y@example.test"},
    {"recipient": "Display <to@example.test>"}, {"recipient": "a@@b"},
    {"username": "user"}, {"password": {"kind": "env", "name": "KEY"}},
    {"username": "user", "password": "plaintext"}, {"tls": "auto"}, {"unknown": True},
])
def test_reject_invalid_options_without_network(changes):
    with pytest.raises(LogAgentError):
        validate_instance(options(**changes), EmailChannelType.options_schema)


async def test_plugin_registration_and_credential_normalization(tmp_path):
    registry = PluginRegistry([], builtin_channels=[EmailChannelType()])
    report = await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    assert not report.errors
    assert {item.name for item in report.registered if item.kind == "channel"} == {"email"}
    store = ResourceStore(tmp_path / "resources.json", channel_register=registry.channelRegister)
    supplied = options(username="user", password={"kind": "env", "name": "KEY"})
    supplied.pop("tls")
    saved = store.save("channels", ChannelConfig(id="email", channel="email", options=supplied))
    assert saved.options["tls"] == "starttls"
    assert saved.options["password"] == {"kind": "env", "name": "KEY"}


async def test_actual_data_mime_and_resident_connection():
    async with smtp_server() as server:
        channel = EmailChannel(config(server.port), None)
        await channel.start()
        assert server.connections == 0
        await channel.send(note(), options={"recipient": "to@example.test"})
        await channel.send(note(text="next", output_id="second"), options={"recipient": "to@example.test"})
        assert server.connections == 1 and len(server.messages) == 2
        first = BytesParser(policy=policy.default).parsebytes(server.messages[0])
        assert first["From"] == "from@example.test" and first["To"] == "to@example.test"
        assert str(first["Subject"]) == "日报"
        assert first.get_content_type() == "text/plain"
        assert first.get_content_charset() == "utf-8"
        assert first.get_content() == "第一行\n第二行"
        assert "must-not-be-used" not in str(first)
        assert first["Message-ID"] != BytesParser(policy=policy.default).parsebytes(server.messages[1])["Message-ID"]
        await channel.stop()
        await channel.stop()
        assert server.commands.count(b"DATA") == 2 and server.commands.count(b"QUIT") == 1


async def test_same_account_concurrent_recipients_reuse_connection_and_do_not_drift(tmp_path):
    class AccountType(EmailChannelType):
        def __init__(self):
            self.created = []

        async def create(self, config, credentials):
            assert "recipient" not in config.options
            self.created.append(config)
            return await super().create(config, credentials)

    account = AccountType()
    registry = PluginRegistry([], builtin_channels=[account])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    manager = ChannelManager(registry.channelRegister)
    async with smtp_server() as server:
        first = config(server.port)
        second = config(server.port)
        second.options["recipient"] = "second@example.test"
        try:
            results = await asyncio.gather(
                manager.send(first, note()),
                manager.send(second, note(output_id="second")),
            )
            assert [result.status for result in results] == ["success", "success"]
            assert server.connections == len(account.created) == 1
            recipients = [BytesParser(policy=policy.default).parsebytes(raw)["To"]
                          for raw in server.messages]
            assert sorted(recipients) == ["second@example.test", "to@example.test"]
            assert (await manager.send(first, note(output_id="original"))).status == "success"
            assert BytesParser(policy=policy.default).parsebytes(server.messages[-1])["To"] == "to@example.test"
        finally:
            await manager.stop()


async def test_direct_email_call_requires_explicit_recipient_even_with_saved_default():
    channel = EmailChannel(config(2525), None)
    with pytest.raises(LogAgentError):
        await channel.send(note(), options={})
    assert channel._client is None


@pytest.mark.parametrize("mode,uncertain,submissions", [
    ("recipient", False, 0), ("reject", False, 1), ("drop", True, 1), ("timeout", True, 1),
])
async def test_rejections_disconnects_and_timeouts_never_retry(mode, uncertain, submissions):
    async with smtp_server(mode) as server:
        manager = ChannelManager(Register())
        result = await manager.send(config(server.port, timeout=.1), note())
        assert result.status in ("failed", "timeout") and result.attempts == 1
        assert result.error.details["delivery_uncertain"] is uncertain
        assert "test-private" not in result.model_dump_json()
        assert len(server.messages) == submissions
        assert server.connections == 1
        await manager.stop()


async def test_authentication_rejection_is_definite_and_redacted():
    class Credentials:
        async def resolve(self, value):
            return "test-private"
    async with smtp_server() as server:
        channel = EmailChannel(config(server.port, username="user", password={"kind": "env", "name": "KEY"}), Credentials())
        await channel.start()
        with pytest.raises(ChannelDeliveryError) as error:
            await channel.send(note(), options={"recipient": "to@example.test"})
        assert not error.value.uncertain
        assert error.value.details["stage"] == "authenticate"
        assert error.value.details["smtp_code"] == 535
        assert "test-private" not in error.value.info.model_dump_json()
        assert not server.messages and server.commands.count(b"AUTH") == 1
        await channel.stop()


async def test_starttls_is_required_and_never_silently_downgraded():
    async with smtp_server() as server:
        channel = EmailChannel(config(server.port, tls="starttls"), None)
        await channel.start()
        with pytest.raises(ChannelDeliveryError) as error:
            await channel.send(note(), options={"recipient": "to@example.test"})
        assert not error.value.uncertain
        assert not server.messages and b"MAIL" not in server.commands
        await channel.stop()


async def test_accepted_then_disconnected_remains_success_and_next_send_reconnects():
    async with smtp_server("accepted_drop") as server:
        channel = EmailChannel(config(server.port), None)
        await channel.start()
        await channel.send(note(), options={"recipient": "to@example.test"})
        for _ in range(5):
            await asyncio.sleep(0)
        assert not channel._client.is_connected
        await channel.send(note(output_id="second"), options={"recipient": "to@example.test"})
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(server.messages) == 2 and server.connections == 2
        await channel.stop()


async def test_cancellation_after_data_never_submits_again():
    async with smtp_server("timeout") as server:
        channel = EmailChannel(config(server.port), None)
        await channel.start()
        sending = asyncio.create_task(channel.send(note(), options={"recipient": "to@example.test"}))
        await server.data_received.wait()
        sending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sending
        assert len(server.messages) == 1
        assert not channel._client.is_connected
        await channel.stop()


async def test_title_header_injection_fails_before_connect():
    async with smtp_server() as server:
        channel = EmailChannel(config(server.port), None)
        await channel.start()
        with pytest.raises(ChannelDeliveryError) as error:
            await channel.send(note(title="test\r\nBcc: injected@example.test"), options={"recipient": "to@example.test"})
        assert not error.value.uncertain and server.connections == 0
        await channel.stop()


async def test_implicit_tls_never_sends_plaintext_smtp():
    received = asyncio.Future()
    async def reject_tls(reader, writer):
        try:
            received.set_result(await reader.read(1))
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(reject_tls, "127.0.0.1", 0)
    channel = EmailChannel(config(server.sockets[0].getsockname()[1], tls="implicit"), None)
    try:
        await channel.start()
        with pytest.raises(ChannelDeliveryError) as error:
            await channel.send(note(), options={"recipient": "to@example.test"})
        assert not error.value.uncertain and error.value.details["stage"] == "connect"
        assert await received == b"\x16"  # TLS handshake record, never an SMTP command.
    finally:
        await channel.stop()
        server.close()
        await server.wait_closed()


async def test_missing_resolver_never_authenticates_or_submits():
    async with smtp_server() as server:
        channel = EmailChannel(config(server.port, username="user", password={"kind": "env", "name": "KEY"}), None)
        await channel.start()
        with pytest.raises(ChannelDeliveryError) as error:
            await channel.send(note(), options={"recipient": "to@example.test"})
        assert error.value.code == "credential_resolver_missing"
        assert b"AUTH" not in server.commands and not server.messages
        await channel.stop()


async def test_cancelling_queued_send_does_not_close_active_smtp_transaction():
    async with smtp_server("hold") as server:
        channel = EmailChannel(config(server.port), None)
        await channel.start()
        first = asyncio.create_task(channel.send(note(), options={"recipient": "to@example.test"}))
        await server.data_received.wait()
        queued = asyncio.create_task(channel.send(note(output_id="queued"), options={"recipient": "to@example.test"}))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert channel._client.is_connected
        server.release.set()
        await first
        assert len(server.messages) == 1
        await channel.stop()


async def test_reused_connection_obeys_current_snapshot_timeout():
    async with smtp_server() as server:
        manager = ChannelManager(Register())
        first = await manager.send(config(server.port, timeout=.1), note())
        assert first.status == "success"
        server.mode = "hold"
        server.data_received.clear()
        sending = asyncio.create_task(manager.send(config(server.port, timeout=1), note(output_id="second")))
        await server.data_received.wait()
        await asyncio.sleep(.15)
        assert not sending.done()
        server.release.set()
        assert (await sending).status == "success"
        assert server.connections == 1 and len(server.messages) == 2
        await manager.stop()
