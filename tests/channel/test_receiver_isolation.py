"""Optional receiver failures must not abort startup of unrelated channels."""

import asyncio

import pytest

from workflowweave.channel import ChannelManager
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import ChannelConfig, Notification


class _Instance:
    def __init__(self, config, owner):
        self.config = config
        self.owner = owner
        self.handler = None
        self.connect_calls = 0
        self.stop_calls = 0
        self.entered = asyncio.Event()

    def fail(self, stage):
        if self.config.id == "broken" and self.owner.failure == stage:
            raise RuntimeError("secret-value must not appear in diagnostics")

    async def start(self):
        self.fail("start")

    async def start_receiving(self, handler):
        self.connect_calls += 1
        self.handler = handler
        self.entered.set()
        self.fail("receive")
        if self.config.id == "broken" and self.owner.failure == "timeout":
            await asyncio.Event().wait()

    async def stop_receiving(self):
        self.stop_calls += 1
        if self.config.id == "broken" and self.owner.cleanup_fails:
            raise RuntimeError("secret-value cleanup failure")
        self.handler = None

    async def stop(self):
        await self.stop_receiving()

    async def send(self, notification, *, options):
        pass


class _Type:
    name = "test"
    capabilities = ["notification", "conversation"]
    options_schema = {"type": "object"}

    def __init__(self, failure):
        self.failure = failure
        self.cleanup_fails = False
        self.instances = {}

    async def create(self, config, credentials):
        if config.id == "broken" and self.failure == "create":
            raise RuntimeError("secret-value creation failure")
        instance = _Instance(config, self)
        self.instances[config.id] = instance
        return instance


class _Registry:
    def __init__(self, channel):
        self.channel = channel

    def get(self, name):
        return self.channel if name == "test" else None

    def describe(self):
        return []


def _config(ident):
    return ChannelConfig(id=ident, channel="test", agent_enabled=True, timeout=0.05)


@pytest.mark.parametrize("stage", ["create", "start", "receive", "timeout"])
async def test_optional_receiver_failure_is_isolated_and_recoverable(stage, caplog):
    channel = _Type(stage)
    manager = ChannelManager(_Registry(channel))
    configs = [_config(ident) for ident in ("before", "broken", "after")]
    try:
        async with asyncio.timeout(1):
            await manager.configure(configs)
        assert set(manager.configs) == {"before", "after"}
        assert manager.active_operations == 0
        error = manager.receiver_errors["broken"]
        assert error.code == (
            "channel_receiver_timeout" if stage == "timeout" else "channel_receiver_start_failed"
        )
        assert error.details["resources"] == ["broken"]
        assert "secret-value" not in error.model_dump_json()
        assert "secret-value" not in caplog.text
        assert "channel_receiver_start_failed" in caplog.text
        if stage in {"receive", "timeout"}:
            assert channel.instances["broken"].handler is None
            assert channel.instances["broken"].stop_calls == 1
            receipt = await manager.send(configs[1], Notification(
                session_id="workflow", output_id="notice", text="still sendable",
            ))
            assert receipt.status == "success"
        channel.failure = None
        await manager.configure(configs)
        assert manager.receiver_errors == {}
        assert set(manager.configs) == {"before", "broken", "after"}
        assert channel.instances["before"].connect_calls == 1
        assert channel.instances["after"].connect_calls == 1
    finally:
        await manager.stop()


@pytest.mark.parametrize("change", ["disable", "delete"])
async def test_removed_receiver_clears_startup_error(change):
    channel = _Type("receive")
    manager = ChannelManager(_Registry(channel))
    config = _config("broken")
    try:
        await manager.configure([config])
        assert manager.receiver_errors
        await manager.configure(
            [config.model_copy(update={"enabled": False})] if change == "disable" else []
        )
        assert manager.receiver_errors == {}
    finally:
        await manager.stop()


async def test_failed_cleanup_is_visible_and_must_finish_before_receiver_retry():
    channel = _Type("receive")
    channel.cleanup_fails = True
    manager = ChannelManager(_Registry(channel))
    configs = [_config("broken"), _config("healthy")]
    try:
        await manager.configure(configs)
        assert set(manager.configs) == {"healthy"}
        error = manager.receiver_errors["broken"]
        assert error.code == "channel_receiver_cleanup_failed"
        assert "secret-value" not in error.model_dump_json()
        receiver = channel.instances["broken"]
        stale_callback = receiver.handler
        assert stale_callback is not None
        with pytest.raises(WorkFLowWeaveError) as rejected:
            await stale_callback(None)
        assert rejected.value.code == "channel_disabled"
        channel.failure = None
        await manager.configure(configs)
        assert receiver.connect_calls == 1
        assert manager.receiver_errors["broken"].code == "channel_receiver_cleanup_failed"
        channel.cleanup_fails = False
        await manager.configure(configs)
        assert receiver.connect_calls == 2
        assert manager.receiver_errors == {}
    finally:
        channel.cleanup_fails = False
        await manager.stop()


async def test_account_change_cannot_bypass_failed_receiver_cleanup():
    channel = _Type("receive")
    channel.cleanup_fails = True
    manager = ChannelManager(_Registry(channel))
    original = _config("broken")
    replacement = original.model_copy(update={"options": {"account": "replacement"}})
    try:
        await manager.configure([original])
        old = channel.instances["broken"]
        channel.failure = None
        await manager.configure([replacement])
        assert channel.instances["broken"] is old
        assert manager.configs == {}
        await manager.configure([])
        assert manager.receiver_errors["broken"].code == "channel_receiver_cleanup_failed"
        channel.cleanup_fails = False
        await manager.configure([replacement])
        assert old.handler is None
        assert channel.instances["broken"] is not old
        assert manager.receiver_errors == {}
    finally:
        channel.cleanup_fails = False
        await manager.stop()


async def test_failed_initialization_cleanup_blocks_duplicate_instance_until_retry():
    channel = _Type("start")
    channel.cleanup_fails = True
    manager = ChannelManager(_Registry(channel))
    config = _config("broken")
    try:
        await manager.configure([config, _config("healthy")])
        old = channel.instances["broken"]
        assert set(manager.configs) == {"healthy"}
        assert manager.receiver_errors["broken"].code == "channel_receiver_cleanup_failed"
        channel.failure = None
        await manager.configure([config, _config("healthy")])
        assert channel.instances["broken"] is old
        channel.cleanup_fails = False
        await manager.configure([config, _config("healthy")])
        assert channel.instances["broken"] is not old
        assert manager.receiver_errors == {}
        assert not manager._retired
    finally:
        channel.cleanup_fails = False
        await manager.stop()


async def test_configuration_cancellation_is_not_reported_as_optional_failure():
    channel = _Type("timeout")
    manager = ChannelManager(_Registry(channel))
    config = _config("broken").model_copy(update={"timeout": 10})
    task = asyncio.create_task(manager.configure([config, _config("after")]))
    try:
        async with asyncio.timeout(1):
            while "broken" not in channel.instances:  # noqa: ASYNC110
                await asyncio.sleep(0)
            receiver = channel.instances["broken"]
            await receiver.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert manager.configs == {}
        assert manager.receiver_errors == {}
        assert "after" not in channel.instances
        assert receiver.handler is None
        assert manager.active_operations == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await manager.stop()
