"""通知分支真实重叠、持久意图屏障和稳定结果顺序。"""

import asyncio

from logagent.models import DeliveryResult, ErrorInfo
from tests.workflow.helpers import archived, snapshot
from tests.workflow.test_workflow_recovery import close, service


async def test_independent_channels_overlap_and_failures_are_isolated(tmp_path):
    w, store, _, _, _ = service(tmp_path / "runs.sqlite3")
    entered = {cid: asyncio.Event() for cid in ("one", "two")}
    release = asyncio.Event()

    class Channels:
        async def send(self, config, notification):
            intent = await asyncio.to_thread(archived, store, "run", f"intent:{notification.output_id}:{config.id}")
            assert intent is not None
            entered[config.id].set()
            await release.wait()
            return DeliveryResult(
                channel_id=config.id, output_id=notification.output_id,
                status="failed" if config.id == "one" else "success", attempts=1,
                error=ErrorInfo(code="rejected", message="rejected") if config.id == "one" else None,
            )

    w.channel_manager = Channels()
    try:
        await w.trigger(snapshot(tasks=("first",)), session_id="run")
        async with asyncio.timeout(5):
            await asyncio.gather(*(event.wait() for event in entered.values()))
        release.set()
        result = await w.wait("run")
        assert result.status == "partial"
        assert [(d.channel_id, d.status) for d in result.deliveries] == [("one", "failed"), ("two", "success")]
        record = await w.get_session("run")
        assert [(p.channel_id, p.status) for p in record.progress if p.event == "delivery"] == [("one", "failed"), ("two", "success")]
    finally:
        release.set()
        await close(w, store)
