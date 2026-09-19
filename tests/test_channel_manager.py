import asyncio
import time

import pytest

from logagent.channel import ChannelDeliveryError, ChannelManager
from logagent.errors import LogAgentError
from logagent.models import CapabilityDescription, ChannelConfig, Notification


class _Register:
    def __init__(self, channel_type):
        self._channel_type = channel_type

    def get(self, name):
        return self._channel_type if name == "test" else None

    def describe(self):
        return []


class _View:
    def __init__(self, channels):
        self._channels = dict(channels)

    def get(self, name):
        return self._channels.get(name)

    def describe(self):
        return [
            CapabilityDescription(
                kind="channel",
                name=channel.name,
                description=channel.name,
                plugin=channel.owner,
                capabilities=["notification"],
                options_schema={"type": "object"},
            )
            for channel in self._channels.values()
        ]

    def diagnostics(self, name):
        return []


class _ChannelType:
    capabilities = ["notification"]
    options_schema = {"type": "object", "additionalProperties": True}

    def __init__(self, create):
        self._create = create
        self.create_calls = 0

    async def create(self, config, credentials):
        self.create_calls += 1
        return await self._create(config)


def _config(*, target: str = "one", timeout: float = 1.0) -> ChannelConfig:
    return ChannelConfig(
        id="target",
        channel="test",
        options={"target": target},
        timeout=timeout,
    )


def _notification(text: str) -> Notification:
    return Notification(session_id="session", output_id=text, text=text)


def _manager(channel_type, *, stop_timeout: float = 1.0) -> ChannelManager:
    return ChannelManager(
        _Register(channel_type),
        stop_timeout=stop_timeout,
    )


def _owned_type(name, owner, create):
    class OwnedType(_ChannelType):
        pass

    channel_type = OwnedType(create)
    channel_type.name = name
    channel_type.owner = owner
    return channel_type


async def test_concurrent_first_send_initializes_once():
    start_entered = asyncio.Event()
    release_start = asyncio.Event()

    class Instance:
        def __init__(self):
            self.start_calls = 0
            self.sends = []

        async def start(self):
            self.start_calls += 1
            start_entered.set()
            await release_start.wait()

        async def send(self, notification, *, options):
            self.sends.append(notification.text)

        async def stop(self):
            return None

    instance = Instance()

    async def create(_config):
        return instance

    channel_type = _ChannelType(create)
    manager = _manager(channel_type)
    config = _config()

    first = asyncio.create_task(manager.send(config, _notification("first")))
    await start_entered.wait()
    second = asyncio.create_task(manager.send(config, _notification("second")))
    await asyncio.sleep(0)
    release_start.set()

    results = await asyncio.gather(first, second)
    assert [result.status for result in results] == ["success", "success"]
    assert channel_type.create_calls == 1
    assert instance.start_calls == 1
    assert instance.sends == ["first", "second"]
    await manager.stop()


async def test_old_snapshot_and_new_config_keep_separate_instances():
    instances = []

    class Instance:
        def __init__(self, target):
            self.target = target
            self.sends = []

        async def start(self):
            return None

        async def send(self, notification, *, options):
            self.sends.append(notification.text)

        async def stop(self):
            return None

    async def create(config):
        instance = Instance(config.options["target"])
        instances.append(instance)
        return instance

    channel_type = _ChannelType(create)
    manager = _manager(channel_type)
    old = _config(target="old")
    new = _config(target="new")

    assert (await manager.send(old, _notification("old-first"))).status == "success"
    assert (await manager.send(new, _notification("new-first"))).status == "success"
    assert (await manager.send(old, _notification("old-second"))).status == "success"

    assert channel_type.create_calls == 2
    assert [instance.target for instance in instances] == ["old", "new"]
    assert instances[0].sends == ["old-first", "old-second"]
    assert instances[1].sends == ["new-first"]
    await manager.stop()


async def test_total_timeout_covers_waiting_for_instance_initialization():
    start_entered = asyncio.Event()
    release_start = asyncio.Event()

    class Instance:
        async def start(self):
            start_entered.set()
            await release_start.wait()

        async def send(self, notification, *, options):
            return None

        async def stop(self):
            return None

    async def create(_config):
        return Instance()

    channel_type = _ChannelType(create)
    manager = _manager(channel_type)
    first = asyncio.create_task(manager.send(_config(), _notification("first")))
    await start_entered.wait()

    result = await asyncio.wait_for(
        manager.send(_config(timeout=0.05), _notification("waiting")), 1.0
    )

    assert result.status == "timeout"
    assert result.attempts == 0
    assert result.error.details["delivery_uncertain"] is False
    release_start.set()
    assert (await first).status == "success"
    await manager.stop()


async def test_total_timeout_covers_create_phase():
    create_entered = asyncio.Event()

    async def create(_config):
        create_entered.set()
        await asyncio.Future()

    channel_type = _ChannelType(create)
    manager = _manager(channel_type)

    result = await asyncio.wait_for(
        manager.send(_config(timeout=0.05), _notification("create")), 1.0
    )

    assert create_entered.is_set()
    assert channel_type.create_calls == 1
    assert result.status == "timeout"
    assert result.attempts == 0
    assert result.error.details["delivery_uncertain"] is False
    await manager.stop()


async def test_timeout_after_plugin_send_starts_is_uncertain():
    send_entered = asyncio.Event()

    class Instance:
        def __init__(self):
            self.stop_calls = 0

        async def start(self):
            return None

        async def send(self, notification, *, options):
            send_entered.set()
            await asyncio.Future()

        async def stop(self):
            self.stop_calls += 1

    instance = Instance()

    async def create(_config):
        return instance

    manager = _manager(_ChannelType(create))
    result = await asyncio.wait_for(
        manager.send(_config(timeout=0.05), _notification("send")), 1.0
    )

    assert send_entered.is_set()
    assert result.status == "timeout"
    assert result.attempts == 1
    assert result.error.details["delivery_uncertain"] is True
    await manager.stop()
    assert instance.stop_calls == 1


async def test_cancelled_plugin_send_propagates_and_instance_is_reused():
    send_entered = asyncio.Event()

    class Instance:
        def __init__(self):
            self.start_calls = 0
            self.send_calls = 0
            self.stop_calls = 0

        async def start(self):
            self.start_calls += 1

        async def send(self, notification, *, options):
            self.send_calls += 1
            if self.send_calls == 1:
                send_entered.set()
                await asyncio.Future()

        async def stop(self):
            self.stop_calls += 1

    instance = Instance()

    async def create(_config):
        return instance

    channel_type = _ChannelType(create)
    manager = _manager(channel_type)
    config = _config()
    cancelled = asyncio.create_task(manager.send(config, _notification("cancelled")))
    await asyncio.wait_for(send_entered.wait(), 1)

    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled

    assert cancelled.cancelled()
    result = await manager.send(config, _notification("retry"))

    assert result.status == "success"
    assert result.attempts == 1
    assert channel_type.create_calls == 1
    assert instance.start_calls == 1
    assert instance.send_calls == 2
    await manager.stop()
    assert instance.stop_calls == 1


async def test_cancelled_create_propagates_and_retry_creates_instance():
    create_entered = asyncio.Event()

    class Instance:
        def __init__(self):
            self.start_calls = 0
            self.sends = []
            self.stop_calls = 0

        async def start(self):
            self.start_calls += 1

        async def send(self, notification, *, options):
            self.sends.append(notification.text)

        async def stop(self):
            self.stop_calls += 1

    instance = Instance()

    async def create(_config):
        if create_entered.is_set():
            return instance
        create_entered.set()
        await asyncio.Future()

    channel_type = _ChannelType(create)
    manager = _manager(channel_type)
    config = _config()
    cancelled = asyncio.create_task(manager.send(config, _notification("cancelled")))
    await asyncio.wait_for(create_entered.wait(), 1)

    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled

    assert cancelled.cancelled()
    assert channel_type.create_calls == 1
    result = await manager.send(config, _notification("retry"))

    assert result.status == "success"
    assert result.attempts == 1
    assert channel_type.create_calls == 2
    assert instance.start_calls == 1
    assert instance.sends == ["retry"]
    await manager.stop()
    assert instance.stop_calls == 1


async def test_cancelled_start_propagates_and_retry_creates_instance():
    start_entered = asyncio.Event()
    instances = []

    class Instance:
        def __init__(self):
            self.start_calls = 0
            self.sends = []
            self.stop_calls = 0

        async def start(self):
            self.start_calls += 1
            if len(instances) == 1:
                start_entered.set()
                await asyncio.Future()

        async def send(self, notification, *, options):
            self.sends.append(notification.text)

        async def stop(self):
            self.stop_calls += 1

    async def create(_config):
        instance = Instance()
        instances.append(instance)
        return instance

    channel_type = _ChannelType(create)
    manager = _manager(channel_type)
    config = _config()
    cancelled = asyncio.create_task(manager.send(config, _notification("cancelled")))
    await asyncio.wait_for(start_entered.wait(), 1)

    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled

    assert cancelled.cancelled()
    assert len(instances) == 1
    assert instances[0].stop_calls == 1
    result = await manager.send(config, _notification("retry"))

    assert result.status == "success"
    assert result.attempts == 1
    assert channel_type.create_calls == 2
    assert len(instances) == 2
    assert instances[1].start_calls == 1
    assert instances[1].sends == ["retry"]
    await manager.stop()
    assert instances[1].stop_calls == 1


async def test_stop_after_cancelled_send_completes_and_blocks_later_send():
    send_entered = asyncio.Event()

    class Instance:
        def __init__(self):
            self.send_calls = 0
            self.stop_calls = 0

        async def start(self):
            return None

        async def send(self, notification, *, options):
            self.send_calls += 1
            send_entered.set()
            await asyncio.Future()

        async def stop(self):
            self.stop_calls += 1

    instance = Instance()

    async def create(_config):
        return instance

    channel_type = _ChannelType(create)
    manager = _manager(channel_type)
    config = _config()
    cancelled = asyncio.create_task(manager.send(config, _notification("cancelled")))
    await asyncio.wait_for(send_entered.wait(), 1)

    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled

    await asyncio.wait_for(manager.stop(), 1)
    result = await manager.send(config, _notification("after-stop"))

    assert result.status == "failed"
    assert result.attempts == 0
    assert result.error.details["delivery_uncertain"] is False
    assert channel_type.create_calls == 1
    assert instance.send_calls == 1
    assert instance.stop_calls == 1


async def test_blocking_prepare_past_budget_is_a_timeout_receipt():
    class Instance:
        def __init__(self):
            self.stop_calls = 0

        async def start(self):
            return None

        async def send(self, notification, *, options):
            raise AssertionError("send must not be called")

        async def stop(self):
            self.stop_calls += 1

    instance = Instance()

    async def create(_config):
        # A plugin that blocks the loop past the deadline never sees the
        # asyncio.timeout cancellation, so the manager enforces the budget.
        time.sleep(0.05)  # noqa: ASYNC251 - blocking plugin code is the case under test
        return instance

    manager = _manager(_ChannelType(create))
    result = await manager.send(_config(timeout=0.01), _notification("late"))

    assert result.status == "timeout"
    assert result.attempts == 0
    assert result.error.details["delivery_uncertain"] is False
    assert instance.stop_calls == 1
    await manager.stop()


async def test_plugin_timeout_error_stays_a_delivery_failure():
    class Instance:
        async def start(self):
            return None

        async def send(self, notification, *, options):
            raise TimeoutError("provider deadline")

        async def stop(self):
            return None

    async def create(_config):
        return Instance()

    manager = _manager(_ChannelType(create))
    result = await manager.send(_config(), _notification("failed"))

    assert result.status == "failed"
    assert result.attempts == 1
    assert result.error.code == "delivery_failed"
    assert result.error.details["delivery_uncertain"] is True
    await manager.stop()


async def test_stop_waits_for_in_flight_send_and_repeat_stop():
    send_entered = asyncio.Event()
    release_send = asyncio.Event()
    stop_entered = asyncio.Event()
    release_stop = asyncio.Event()

    class Instance:
        def __init__(self):
            self.events = []
            self.stop_calls = 0

        async def start(self):
            return None

        async def send(self, notification, *, options):
            self.events.append("send")
            send_entered.set()
            await release_send.wait()
            self.events.append("send_done")

        async def stop(self):
            self.stop_calls += 1
            self.events.append("stop")
            stop_entered.set()
            await release_stop.wait()
            self.events.append("stop_done")

    instance = Instance()

    async def create(_config):
        return instance

    manager = _manager(_ChannelType(create))
    send_task = asyncio.create_task(manager.send(_config(), _notification("send")))
    await send_entered.wait()

    first_stop = asyncio.create_task(manager.stop())
    second_stop = asyncio.create_task(manager.stop())
    await asyncio.sleep(0)
    assert not first_stop.done()
    assert not second_stop.done()
    assert instance.stop_calls == 0

    release_send.set()
    await stop_entered.wait()
    assert not first_stop.done()
    assert not second_stop.done()

    release_stop.set()
    assert (await send_task).status == "success"
    await asyncio.gather(first_stop, second_stop)
    assert instance.stop_calls == 1
    assert instance.events == ["send", "send_done", "stop", "stop_done"]


async def test_initialization_failure_releases_instance_and_preserves_cleanup_error():
    class Instance:
        def __init__(self):
            self.stop_calls = 0

        async def start(self):
            raise RuntimeError("start failed")

        async def send(self, notification, *, options):
            raise AssertionError("send must not be called")

        async def stop(self):
            self.stop_calls += 1
            raise ValueError("cleanup failed")

    instance = Instance()

    async def create(_config):
        return instance

    manager = _manager(_ChannelType(create))
    result = await manager.send(_config(), _notification("failed"))

    assert result.status == "failed"
    assert result.attempts == 0
    assert result.error.details["delivery_uncertain"] is False
    assert result.error.details["initialization_error"]["details"]["exception_type"] == (
        "RuntimeError"
    )
    assert result.error.details["cleanup_error"]["details"]["exception_type"] == "ValueError"
    assert instance.stop_calls == 1


async def test_send_after_admission_closes_does_not_reach_stopped_instance():
    class Instance:
        def __init__(self):
            self.send_calls = 0
            self.stop_calls = 0

        async def start(self):
            return None

        async def send(self, notification, *, options):
            self.send_calls += 1

        async def stop(self):
            self.stop_calls += 1

    instance = Instance()

    async def create(_config):
        return instance

    channel_type = _ChannelType(create)
    manager = _manager(channel_type)

    assert (await manager.send(_config(), _notification("before"))).status == "success"
    await manager.stop()
    result = await manager.send(_config(), _notification("after"))

    assert result.status == "failed"
    assert result.attempts == 0
    assert result.error.details["delivery_uncertain"] is False
    assert channel_type.create_calls == 1
    assert instance.send_calls == 1
    assert instance.stop_calls == 1


async def test_same_instance_sends_are_serialized():
    send_entered = asyncio.Event()
    release_send = asyncio.Event()

    class Instance:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self.send_calls = 0

        async def start(self):
            return None

        async def send(self, notification, *, options):
            self.send_calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                send_entered.set()
                await release_send.wait()
            finally:
                self.active -= 1

        async def stop(self):
            return None

    instance = Instance()

    async def create(_config):
        return instance

    manager = _manager(_ChannelType(create))
    config = _config()
    first = asyncio.create_task(manager.send(config, _notification("first")))
    await send_entered.wait()
    second = asyncio.create_task(manager.send(config, _notification("second")))
    await asyncio.sleep(0.01)

    assert instance.send_calls == 1
    assert instance.max_active == 1

    release_send.set()
    results = await asyncio.gather(first, second)
    assert [result.status for result in results] == ["success", "success"]
    assert instance.max_active == 1
    await manager.stop()


async def test_disabled_config_is_skipped_without_construction():
    channel_type = _ChannelType(lambda _config: pytest.fail("must not create"))
    manager = _manager(channel_type)
    config = _config()
    config.enabled = False

    result = await manager.send(config, _notification("skipped"))

    assert result.status == "skipped"
    assert result.attempts == 0
    assert channel_type.create_calls == 0
    await manager.stop()


async def test_total_timeout_covers_waiting_for_send_lock():
    send_entered = asyncio.Event()
    release_send = asyncio.Event()

    class Instance:
        def __init__(self):
            self.send_calls = 0

        async def start(self):
            return None

        async def send(self, notification, *, options):
            self.send_calls += 1
            send_entered.set()
            await release_send.wait()

        async def stop(self):
            return None

    instance = Instance()

    async def create(_config):
        return instance

    manager = _manager(_ChannelType(create))
    first = asyncio.create_task(manager.send(_config(timeout=1), _notification("first")))
    await send_entered.wait()

    result = await asyncio.wait_for(
        manager.send(_config(timeout=0.05), _notification("waiting")), 1.0
    )

    assert result.status == "timeout"
    assert result.attempts == 0
    assert result.error.details["delivery_uncertain"] is False
    assert instance.send_calls == 1

    release_send.set()
    assert (await first).status == "success"
    await manager.stop()


async def test_channel_delivery_error_preserves_code_message_and_details():
    class Instance:
        async def start(self):
            return None

        async def send(self, notification, *, options):
            raise ChannelDeliveryError(
                "rate_limited",
                "provider rejected the request",
                uncertain=True,
                details={"retry_after": 3},
            )

        async def stop(self):
            return None

    async def create(_config):
        return Instance()

    manager = _manager(_ChannelType(create))
    result = await manager.send(_config(), _notification("failed"))

    assert result.status == "failed"
    assert result.attempts == 1
    assert result.error.code == "rate_limited"
    assert result.error.message == "provider rejected the request"
    assert result.error.details == {"retry_after": 3, "delivery_uncertain": True}
    await manager.stop()


async def test_stop_preserves_every_cleanup_error():
    instances = []

    class Instance:
        def __init__(self, message):
            self.message = message

        async def start(self):
            return None

        async def send(self, notification, *, options):
            return None

        async def stop(self):
            raise RuntimeError(self.message)

    async def create(config):
        instance = Instance(f"cleanup {config.options['target']}")
        instances.append(instance)
        return instance

    manager = _manager(_ChannelType(create))
    await manager.send(_config(target="one"), _notification("one"))
    await manager.send(_config(target="two"), _notification("two"))

    with pytest.raises(LogAgentError) as error:
        await manager.stop()

    assert error.value.code == "channel_stop_failed"
    assert len(error.value.details["errors"]) == 2
    assert all(item["details"]["exception_type"] == "RuntimeError"
               for item in error.value.details["errors"])
    assert "cleanup one" not in error.value.info.model_dump_json()
    assert "cleanup two" not in error.value.info.model_dump_json()


async def test_release_waits_for_active_send_and_allows_a_new_instance():
    send_entered = asyncio.Event()
    release_send = asyncio.Event()
    instances = []

    class Instance:
        def __init__(self):
            self.stop_calls = 0

        async def start(self):
            return None

        async def send(self, notification, *, options):
            if notification.text == "slow":
                send_entered.set()
                await release_send.wait()

        async def stop(self):
            self.stop_calls += 1

    async def create(_config):
        instance = Instance()
        instances.append(instance)
        return instance

    view = _View({"test": _owned_type("test", "owner", create)})
    manager = ChannelManager(view, stop_timeout=1)
    config = _config()

    assert (await manager.send(config, _notification("first"))).status == "success"
    active = asyncio.create_task(manager.send(config, _notification("slow")))
    await send_entered.wait()
    releasing = asyncio.create_task(manager.release(config))
    await asyncio.sleep(0)

    assert instances[0].stop_calls == 0

    release_send.set()
    assert (await active).status == "success"
    await releasing

    assert instances[0].stop_calls == 1
    assert (await manager.send(config, _notification("new"))).status == "success"
    assert len(instances) == 2
    await manager.stop()
    assert instances[1].stop_calls == 1


async def test_reload_register_only_releases_removed_types_after_send():
    send_entered = asyncio.Event()
    release_send = asyncio.Event()
    instances = {}

    class Instance:
        def __init__(self, name):
            self.name = name
            self.stop_calls = 0

        async def start(self):
            return None

        async def send(self, notification, *, options):
            if self.name == "drop" and notification.text == "slow":
                send_entered.set()
                await release_send.wait()

        async def stop(self):
            self.stop_calls += 1

    def create(name):
        async def make(_config):
            instance = Instance(name)
            instances[name] = instance
            return instance

        return make

    drop = _owned_type("drop", "alpha", create("drop"))
    keep = _owned_type("keep", "beta", create("keep"))
    manager = ChannelManager(_View({"drop": drop, "keep": keep}), stop_timeout=1)
    drop_config = ChannelConfig(id="drop-config", channel="drop", options={"target": "drop"})
    keep_config = ChannelConfig(id="keep-config", channel="keep", options={"target": "keep"})

    assert (await manager.send(drop_config, _notification("first"))).status == "success"
    assert (await manager.send(keep_config, _notification("keep"))).status == "success"
    active = asyncio.create_task(manager.send(drop_config, _notification("slow")))
    await send_entered.wait()

    reloading = asyncio.create_task(manager.reload_register(_View({"keep": keep})))
    await asyncio.sleep(0)
    assert instances["drop"].stop_calls == 0
    assert instances["keep"].stop_calls == 0

    release_send.set()
    assert (await active).status == "success"
    await reloading

    assert instances["drop"].stop_calls == 1
    assert instances["keep"].stop_calls == 0
    missing = await manager.send(drop_config, _notification("missing"))
    assert missing.status == "failed"
    assert missing.attempts == 0
    assert missing.error.code == "channel_missing"
    assert (await manager.send(keep_config, _notification("reused"))).status == "success"
    await manager.stop()
    assert instances["keep"].stop_calls == 1


async def test_unload_owner_waits_for_active_send():
    send_entered = asyncio.Event()
    release_send = asyncio.Event()

    class Instance:
        def __init__(self):
            self.stop_calls = 0

        async def start(self):
            return None

        async def send(self, notification, *, options):
            send_entered.set()
            await release_send.wait()

        async def stop(self):
            self.stop_calls += 1

    instance = Instance()

    async def create(_config):
        return instance

    manager = ChannelManager(
        _View({"test": _owned_type("test", "owner", create)}),
        stop_timeout=1,
    )
    config = ChannelConfig(id="target", channel="test")
    active = asyncio.create_task(manager.send(config, _notification("slow")))
    await send_entered.wait()

    unloading = asyncio.create_task(manager.unload_owner("owner"))
    await asyncio.sleep(0)
    assert instance.stop_calls == 0

    release_send.set()
    assert (await active).status == "success"
    await unloading
    assert instance.stop_calls == 1
    await manager.stop()


@pytest.mark.parametrize("budget", [0, -1, float("nan"), float("inf")])
def test_stop_budget_must_be_positive_and_finite(budget):
    with pytest.raises(ValueError):
        _manager(None, stop_timeout=budget)


async def test_same_name_replacement_releases_old_implementation():
    events = []
    def channel_type(version):
        class Instance:
            async def start(self):
                events.append((version, "start"))
            async def send(self, notification, *, options):
                events.append((version, "send"))
            async def stop(self):
                events.append((version, "stop"))
        async def create(config):
            return Instance()
        return _owned_type("test", "owner", create)
    manager = ChannelManager(_View({"test": channel_type("old")}))
    await manager.send(_config(), _notification("before"))
    await manager.replace_register(_View({"test": channel_type("new")}))
    await manager.send(_config(), _notification("after"))
    await manager.stop()
    assert events == [("old", "start"), ("old", "send"), ("old", "stop"),
                      ("new", "start"), ("new", "send"), ("new", "stop")]


async def test_unload_owner_rejects_new_sends_while_draining():
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []
    class Instance:
        async def start(self):
            pass
        async def send(self, notification, *, options):
            calls.append(notification.text)
            entered.set()
            await finish.wait()
        async def stop(self):
            calls.append("stop")
    async def create(config):
        return Instance()
    manager = ChannelManager(_View({"test": _owned_type("test", "owner", create)}))
    active = asyncio.create_task(manager.send(_config(), _notification("active")))
    await entered.wait()
    unload = asyncio.create_task(manager.unload_owner("owner"))
    await asyncio.sleep(0)
    rejected = await manager.send(_config(), _notification("new"))
    assert rejected.status == "failed" and rejected.attempts == 0
    finish.set()
    assert (await active).status == "success"
    await unload
    rejected = await manager.send(_config(), _notification("after"))
    assert rejected.status == "failed" and calls == ["active", "stop"]
    await manager.stop()


async def test_stop_cancels_overdue_send_then_closes_instance():
    entered = asyncio.Event()
    events = []
    class Instance:
        async def start(self):
            pass
        async def send(self, notification, *, options):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                events.append("send_done")
        async def stop(self):
            events.append("stop")
    async def create(config):
        return Instance()
    manager = _manager(_ChannelType(create), stop_timeout=.02)
    active = asyncio.create_task(manager.send(_config(), _notification("active")))
    await entered.wait()
    await manager.stop()
    with pytest.raises(asyncio.CancelledError):
        await active
    assert events == ["send_done", "stop"]
    assert not manager._entries
    await manager.stop()


async def test_cleanup_timeout_retains_ownership_until_later_stop():
    release = asyncio.Event()
    calls = []
    class Instance:
        async def start(self):
            pass
        async def send(self, notification, *, options):
            pass
        async def stop(self):
            calls.append("stop")
            await release.wait()
    async def create(config):
        return Instance()
    manager = _manager(_ChannelType(create), stop_timeout=.02)
    await manager.send(_config(), _notification("once"))
    with pytest.raises(LogAgentError):
        await manager.stop()
    assert len(manager._entries) == 1
    release.set()
    await manager.stop()
    assert not manager._entries and calls == ["stop"]


async def test_failed_start_cleanup_retains_instance_until_it_finishes():
    release = asyncio.Event()
    calls = []
    class Instance:
        async def start(self):
            raise RuntimeError("secret-start")
        async def stop(self):
            calls.append("stop")
            await release.wait()
    async def create(config):
        return Instance()
    manager = _manager(_ChannelType(create), stop_timeout=.02)
    result = await manager.send(_config(), _notification("bad"))
    assert result.status == "failed" and result.attempts == 0
    assert "secret-start" not in result.model_dump_json()
    assert len(manager._retired) == 1
    release.set()
    await manager.stop()
    assert not manager._retired and calls == ["stop"]


async def test_start_that_swallows_cancellation_cannot_send():
    entered = asyncio.Event()
    calls = []
    class Instance:
        async def start(self):
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                return
        async def send(self, notification, *, options):
            calls.append("send")
        async def stop(self):
            calls.append("stop")
    async def create(config):
        return Instance()
    manager = _manager(_ChannelType(create))
    active = asyncio.create_task(manager.send(_config(), _notification("cancelled")))
    await entered.wait()
    active.cancel()
    with pytest.raises(asyncio.CancelledError):
        await active
    await manager.stop()
    assert calls == ["stop"]


async def test_readonly_registry_wrappers_do_not_recreate_unchanged_instances(tmp_path):
    from logagent.channel import MockFileChannelType
    from logagent.config import PluginRegistry
    from logagent.models import SystemConfig
    registry = PluginRegistry([], builtin_channels=[MockFileChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    manager = ChannelManager(registry.channelRegister)
    config = ChannelConfig(id="file", channel="mock", options={"path": str(tmp_path / "out.txt")})
    assert (await manager.send(config, _notification("first"))).status == "success"
    original = next(iter(manager._entries.values()))
    await manager.replace_register(registry.channelRegister)
    assert next(iter(manager._entries.values())) is original
    assert not original.stopped
    assert (await manager.send(config, _notification("second"))).status == "success"
    await manager.stop()


async def test_failure_diagnostics_log_identity_without_notification_or_exception(caplog):
    async def create(config):
        raise RuntimeError("private-credential")
    manager = _manager(_ChannelType(create))
    await manager.send(_config(), Notification(session_id="session", output_id="output", text="private-body"))
    records = [record for record in caplog.records if record.getMessage() == "notification_failed"]
    assert len(records) == 1
    assert records[0].session_id == "session" and records[0].channel_id == "target"
    assert records[0].error_code == "channel_prepare_failed"
    assert "private" not in str(records[0].__dict__)
    await manager.stop()


async def test_call_options_and_budgets_reuse_instance_without_leaking_into_create():
    created = []
    delivered = []

    class Instance:
        async def start(self):
            pass

        async def send(self, notification, *, options):
            delivered.append(options)

        async def stop(self):
            pass

    async def create(config):
        created.append(config.options)
        return Instance()

    channel_type = _ChannelType(create)
    channel_type.options_schema = {
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "recipient": {"type": "string", "x-logagent-workflow": True},
        },
        "required": ["target", "recipient"],
        "additionalProperties": False,
    }
    manager = _manager(channel_type)
    try:
        for recipient, timeout in (("first", 1.0), ("second", 2.0)):
            config = _config(timeout=timeout).model_copy(
                update={"options": {"target": "account", "recipient": recipient}}
            )
            result = await manager.send(config, _notification(recipient))
            assert result.status == "success" and result.attempts == 1
        assert created == [{"target": "account"}]
        assert delivered == [{"recipient": "first"}, {"recipient": "second"}]
    finally:
        await manager.stop()


@pytest.mark.parametrize("cancel_waiter", [False, True])
async def test_waiting_send_does_not_cancel_instance_release(cancel_waiter):
    stopping = asyncio.Event()
    finish_stop = asyncio.Event()
    calls = []

    class Instance:
        async def start(self):
            pass

        async def send(self, notification, *, options):
            calls.append(notification.text)

        async def stop(self):
            calls.append("stop")
            stopping.set()
            await finish_stop.wait()

    async def create(config):
        return Instance()

    channel_type = _ChannelType(create)
    manager = _manager(channel_type)
    assert (await manager.send(_config(), _notification("first"))).status == "success"
    release = asyncio.create_task(manager.release(_config()))
    await stopping.wait()
    try:
        waiting = asyncio.create_task(manager.send(
            _config(timeout=1.0 if cancel_waiter else 0.01), _notification("waiting")
        ))
        if cancel_waiter:
            await asyncio.sleep(0)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
        else:
            result = await waiting
            assert result.status == "timeout" and result.attempts == 0
            assert result.error.details["delivery_uncertain"] is False
        assert not release.done()
        assert channel_type.create_calls == 1
        assert calls == ["first", "stop"]
    finally:
        finish_stop.set()
        await release
        await manager.stop()


async def test_release_drain_timeout_does_not_fail_waiting_send():
    sending = asyncio.Event()
    finish_send = asyncio.Event()
    delivered = []

    class Instance:
        async def start(self):
            pass

        async def send(self, notification, *, options):
            sending.set()
            await finish_send.wait()
            delivered.append(notification.text)

        async def stop(self):
            pass

    async def create(config):
        return Instance()

    channel_type = _ChannelType(create)
    manager = _manager(channel_type, stop_timeout=0.02)
    first = asyncio.create_task(manager.send(_config(), _notification("first")))
    await sending.wait()
    release = asyncio.create_task(manager.release(_config()))
    await asyncio.sleep(0)
    waiting = asyncio.create_task(manager.send(_config(), _notification("waiting")))
    try:
        with pytest.raises(TimeoutError):
            await release
        assert not waiting.done()
    finally:
        finish_send.set()
        results = await asyncio.gather(first, waiting)
        await manager.stop()
    assert all(result.status == "success" for result in results)
    assert delivered == ["first", "waiting"]
    assert channel_type.create_calls == 1


async def test_stop_waits_for_send_completion_not_caller_task_lifetime(tmp_path):
    from logagent.channel import MockFileChannelType
    from logagent.config import PluginRegistry
    from logagent.models import SystemConfig

    registry = PluginRegistry([], builtin_channels=[MockFileChannelType()])
    await registry.discover_plugins(SystemConfig(plugin_dir=str(tmp_path / "plugins")))
    manager = ChannelManager(registry.channelRegister)
    path = tmp_path / "notifications.txt"
    path.write_text("existing\n", encoding="utf-8")
    config = ChannelConfig(id="file", channel="mock", options={"path": str(path)})
    sent = asyncio.Event()
    finish_caller = asyncio.Event()

    async def caller():
        receipt = await manager.send(config, Notification(
            session_id="acceptance", output_id="report", title="验收",
            text="第一行\n第二行", metadata={"path": str(tmp_path / "wrong.txt")},
        ))
        sent.set()
        await finish_caller.wait()
        return receipt

    task = asyncio.create_task(caller())
    try:
        await asyncio.wait_for(sent.wait(), 1.0)
        await asyncio.wait_for(manager.stop(), 1.0)
        assert not task.done()
        assert path.read_text(encoding="utf-8") == "existing\n验收\n第一行\n第二行\n"
        assert not (tmp_path / "wrong.txt").exists()
    finally:
        finish_caller.set()
        receipt = await task
        await manager.stop()
    assert receipt.status == "success" and receipt.attempts == 1
    assert receipt.channel_id == "file" and receipt.output_id == "report"
    assert receipt.error is None
