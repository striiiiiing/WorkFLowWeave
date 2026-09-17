import asyncio
import errno
import logging
import threading

import pytest

from logagent.channel.errors import ChannelDeliveryError
from logagent.channel.mock import MockFileChannel
from logagent.models import ChannelConfig, Notification


def _channel(path, channel_id="mock"):
    return MockFileChannel(
        ChannelConfig(id=channel_id, channel="mock", options={"path": str(path)})
    )


def _notification(text, *, title="", output_id="output"):
    return Notification(
        session_id="session",
        output_id=output_id,
        title=title,
        text=text,
    )


async def test_send_preserves_readable_multiline_text_and_existing_content(tmp_path):
    path = tmp_path / "notifications.txt"
    path.write_text("existing\n", encoding="utf-8")
    channel = _channel(path)
    await channel.start()
    try:
        await channel.send(_notification("first\nsecond", title="Report"), options={})
        assert path.read_text(encoding="utf-8") == (
            "existing\n"
            "Report\n"
            "first\n"
            "second\n"
        )
    finally:
        await channel.stop()


async def test_concurrent_appends_do_not_interleave(tmp_path):
    path = tmp_path / "concurrent.txt"
    channel = _channel(path)
    messages = [f"message-{index:02d}-" + ("x" * 8192) for index in range(24)]
    await channel.start()
    try:
        await asyncio.gather(
            *(
                channel.send(_notification(message, output_id=f"output-{index}"), options={})
                for index, message in enumerate(messages)
            )
        )
        assert sorted(path.read_text(encoding="utf-8").splitlines()) == sorted(messages)
    finally:
        await channel.stop()


async def test_handler_filter_and_level_do_not_skip_mock_output(tmp_path):
    path = tmp_path / "filtered.txt"
    channel = _channel(path)

    class RejectEverything(logging.Filter):
        def filter(self, record):
            return False

    channel.handler.addFilter(RejectEverything())
    channel.handler.setLevel(logging.CRITICAL + 1)
    await channel.start()
    try:
        await channel.send(_notification("written directly"), options={})
        assert path.read_text(encoding="utf-8") == "written directly\n"
    finally:
        await channel.stop()


async def test_global_logging_disable_and_disabled_root_do_not_skip_mock_output(tmp_path):
    path = tmp_path / "globally-disabled.txt"
    channel = _channel(path)
    previous_disable = logging.root.manager.disable
    previous_root_disabled = logging.root.disabled
    await channel.start()
    try:
        logging.disable(logging.CRITICAL)
        logging.root.disabled = True
        await channel.send(_notification("still written"), options={})
        assert path.read_text(encoding="utf-8") == "still written\n"
    finally:
        logging.disable(previous_disable)
        logging.root.disabled = previous_root_disabled
        await channel.stop()


class _FailingStream:
    def __init__(self, operation, error):
        self.operation = operation
        self.error = error
        self.writes = []

    def write(self, payload):
        if self.operation == "write":
            raise self.error
        self.writes.append(payload)
        return len(payload)

    def flush(self):
        if self.operation == "flush":
            raise self.error

    def close(self):
        pass


@pytest.mark.parametrize("operation", ["write", "flush"])
async def test_write_and_flush_errors_fail_send_with_diagnostics(
    tmp_path, monkeypatch, operation
):
    path = tmp_path / f"{operation}-failure.txt"
    channel = _channel(path)
    await channel.start()
    real_stream = channel.handler._stream
    failure = OSError(errno.ENOSPC, f"injected {operation} failure")
    monkeypatch.setattr(channel.handler, "_stream", _FailingStream(operation, failure))
    try:
        with pytest.raises(ChannelDeliveryError) as caught:
            await channel.send(_notification("not delivered"), options={})
        assert caught.value.code == "mock_write_failed"
        assert caught.value.uncertain is True
        assert caught.value.details["operation"] == operation
        assert caught.value.details["exception_type"] == "OSError"
        assert caught.value.details["errno"] == errno.ENOSPC
    finally:
        monkeypatch.setattr(channel.handler, "_stream", real_stream)
        await channel.stop()


class _FailOnceWriteStream:
    def __init__(self, real_stream):
        self.real_stream = real_stream
        self.calls = 0

    def write(self, payload):
        self.calls += 1
        if self.calls == 1:
            raise OSError(errno.EIO, "injected first-write failure")
        return self.real_stream.write(payload)

    def flush(self):
        self.real_stream.flush()

    def close(self):
        self.real_stream.close()


async def test_each_send_has_an_independent_result(tmp_path, monkeypatch):
    path = tmp_path / "independent-results.txt"
    channel = _channel(path)
    await channel.start()
    real_stream = channel.handler._stream
    failing = _FailOnceWriteStream(real_stream)
    monkeypatch.setattr(channel.handler, "_stream", failing)
    try:
        with pytest.raises(ChannelDeliveryError):
            await channel.send(_notification("first"), options={})
        await channel.send(_notification("second"), options={})
        assert failing.calls == 2
        assert path.read_text(encoding="utf-8") == "second\n"
    finally:
        monkeypatch.setattr(channel.handler, "_stream", real_stream)
        await channel.stop()


class _PartialWriteStream:
    def __init__(self):
        self.preview = ""

    def write(self, payload):
        self.preview += payload[: max(1, len(payload) // 2)]
        return len(self.preview)

    def flush(self):
        pass

    def close(self):
        pass


async def test_partial_write_is_uncertain(tmp_path, monkeypatch):
    path = tmp_path / "partial.txt"
    channel = _channel(path)
    await channel.start()
    real_stream = channel.handler._stream
    monkeypatch.setattr(channel.handler, "_stream", _PartialWriteStream())
    try:
        with pytest.raises(ChannelDeliveryError) as caught:
            await channel.send(_notification("partially delivered"), options={})
        assert caught.value.code == "mock_write_failed"
        assert caught.value.uncertain is True
        assert caught.value.details["operation"] == "write"
        assert caught.value.details["errno"] == errno.EIO
        assert caught.value.details["written"] < caught.value.details["expected"]
    finally:
        monkeypatch.setattr(channel.handler, "_stream", real_stream)
        await channel.stop()


async def test_failure_before_stream_write_is_not_uncertain(tmp_path):
    channel = _channel(tmp_path / "not-started.txt")
    with pytest.raises(ChannelDeliveryError) as caught:
        await channel.send(_notification("not delivered"), options={})
    assert caught.value.code == "mock_write_failed"
    assert caught.value.uncertain is False
    await channel.stop()


class _BlockingStream:
    def __init__(self, real_stream):
        self.real_stream = real_stream
        self.write_started = threading.Event()
        self.release_write = threading.Event()
        self.write_finished = threading.Event()
        self.write_calls = 0

    def write(self, payload):
        self.write_calls += 1
        self.write_started.set()
        if not self.release_write.wait(timeout=5):
            raise TimeoutError("test stream was not released")
        try:
            return self.real_stream.write(payload)
        finally:
            self.write_finished.set()

    def flush(self):
        self.real_stream.flush()

    def close(self):
        self.real_stream.close()


async def test_cancellation_propagates_and_does_not_append_twice(tmp_path, monkeypatch):
    path = tmp_path / "cancelled.txt"
    channel = _channel(path)
    await channel.start()
    real_stream = channel.handler._stream
    blocking = _BlockingStream(real_stream)
    monkeypatch.setattr(channel.handler, "_stream", blocking)
    task = asyncio.create_task(channel.send(_notification("cancelled"), options={}))
    try:
        assert await asyncio.to_thread(blocking.write_started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        blocking.release_write.set()
        assert await asyncio.to_thread(blocking.write_finished.wait, 1)
        monkeypatch.setattr(channel.handler, "_stream", real_stream)
        await channel.stop()
    assert blocking.write_calls == 1
    assert path.read_text(encoding="utf-8") == "cancelled\n"


async def test_shared_handler_stop_is_reference_counted_and_idempotent(tmp_path):
    path = tmp_path / "shared.txt"
    first = _channel(path, "first")
    second = _channel(path, "second")
    assert first.handler is second.handler
    await asyncio.gather(first.start(), second.start())

    await first.stop()
    await first.stop()
    assert first.handler._stream is not None

    await second.stop()
    await second.stop()
    assert second.handler._stream is None


async def test_missing_write_count_cannot_report_success(tmp_path, monkeypatch):
    class Stream(_PartialWriteStream):
        def write(self, payload):
            return None
    channel = _channel(tmp_path / "no-count.txt")
    await channel.start()
    original = channel.handler._stream
    monkeypatch.setattr(channel.handler, "_stream", Stream())
    try:
        with pytest.raises(ChannelDeliveryError) as error:
            await channel.send(_notification("body"), options={})
        assert error.value.uncertain
    finally:
        monkeypatch.setattr(channel.handler, "_stream", original)
        await channel.stop()


async def test_cancelled_start_is_drained_before_close(tmp_path, monkeypatch):
    from logagent.errors import LogAgentError
    monkeypatch.setattr("logagent.channel.mock._STOP_TIMEOUT", .02)
    channel = _channel(tmp_path / "late-start.txt")
    entered, release = threading.Event(), threading.Event()
    original = channel.handler.start
    def delayed_start():
        entered.set()
        assert release.wait(2)
        original()
    monkeypatch.setattr(channel.handler, "start", delayed_start)
    task = asyncio.create_task(channel.start())
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(LogAgentError) as error:
            await channel.stop()
        assert error.value.code == "mock_stop_timeout"
        assert not channel._stop_task.done()
    finally:
        release.set()
        await asyncio.wait_for(asyncio.shield(channel._stop_task), 1)
        await channel.stop()
    assert channel.handler._stream is None
    with pytest.raises(ChannelDeliveryError, match="已关闭"):
        await channel.start()


async def test_stop_waits_for_cancelled_write_and_can_be_awaited_again(tmp_path, monkeypatch):
    from logagent.errors import LogAgentError
    monkeypatch.setattr("logagent.channel.mock._STOP_TIMEOUT", .02)
    path = tmp_path / "pending.txt"
    channel = _channel(path)
    await channel.start()
    blocking = _BlockingStream(channel.handler._stream)
    monkeypatch.setattr(channel.handler, "_stream", blocking)
    send = asyncio.create_task(channel.send(_notification("once"), options={}))
    try:
        assert await asyncio.to_thread(blocking.write_started.wait, 1)
        send.cancel()
        with pytest.raises(asyncio.CancelledError):
            await send
        with pytest.raises(LogAgentError) as error:
            await channel.stop()
        assert error.value.code == "mock_stop_timeout"
    finally:
        blocking.release_write.set()
        await asyncio.wait_for(asyncio.shield(channel._stop_task), 1)
        await channel.stop()
    assert channel.handler._stream is None
    assert path.read_text() == "once\n"


async def test_new_owner_shares_handler_during_close(tmp_path, monkeypatch):
    path = tmp_path / "close-race.txt"
    first = _channel(path, "first")
    await first.start()
    original = first.handler._stream
    closing, release = threading.Event(), threading.Event()
    class ClosingStream:
        def close(self):
            closing.set()
            assert release.wait(2)
            original.close()
    monkeypatch.setattr(first.handler, "_stream", ClosingStream())
    stop = asyncio.create_task(first.stop())
    second = None
    try:
        assert await asyncio.to_thread(closing.wait, 1)
        second = _channel(path, "second")
        assert second.handler is first.handler
        starting = asyncio.create_task(second.start())
        await asyncio.sleep(0)
        assert not starting.done()
    finally:
        release.set()
        await stop
    await starting
    try:
        await second.send(_notification("new owner"), options={})
    finally:
        await second.stop()
    assert path.read_text() == "new owner\n"
