"""Workflow 准入与关闭竞争测试。

使用共享采集/AI/通知替身和真实临时存储，以事件屏障暂停建档和清理，
断言暂停准入等待已受理触发完成，关闭调用方被取消不会遗弃自有清理任务。
只覆盖 Workflow 的生命周期边界，不装配完整应用。
"""

import asyncio

import pytest

from logagent.errors import LogAgentError
from logagent.workflow.execution.runner import WorkflowRunner
from tests.workflow.helpers import AI, Channel, Collector, snapshot


async def test_pause_waits_for_admitted_trigger_snapshot(tmp_path):
    ai = AI(block="first")
    entered, release = asyncio.Event(), asyncio.Event()

    class Resources:
        async def snapshot(self, workflow_id):
            entered.set()
            await release.wait()
            return snapshot()

    workflow = WorkflowRunner(
        Collector(),
        ai,
        Channel(),
        Resources(),
        database=tmp_path / "runs.sqlite3",
    )
    try:
        trigger = asyncio.create_task(workflow.trigger("saved", session_id="admitted"))
        await entered.wait()
        pause = asyncio.create_task(workflow.pause_admission())
        await asyncio.sleep(0)
        assert not pause.done()
        release.set()
        assert await trigger == "admitted"
        assert await pause == 1
        assert workflow.coordinator.contains("admitted")
        with pytest.raises(LogAgentError) as error:
            await workflow.trigger(snapshot(), session_id="later")
        assert error.value.code == "not_ready"
        assert await asyncio.to_thread(workflow.session_store.entry, "later", "created") is None
    finally:
        release.set()
        await workflow.shutdown()


async def test_cancelled_shutdown_caller_does_not_abandon_owned_cleanup(tmp_path):
    workflow = WorkflowRunner(Collector(), AI(), Channel(), database=tmp_path / "runs.sqlite3")
    await workflow.start()
    entered, release = asyncio.Event(), asyncio.Event()
    original = workflow.coordinator.shutdown

    async def delayed():
        entered.set()
        await release.wait()
        await original()

    workflow.coordinator.shutdown = delayed
    caller = asyncio.create_task(workflow.shutdown())
    await entered.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    # Cleanup still owns the database until its dependent tasks have drained.
    assert workflow.session_store.session_ids() == []
    release.set()
    await workflow.shutdown()
    with pytest.raises(LogAgentError) as error:
        workflow.session_store.session_ids()
    assert error.value.code == "storage_closed"
    await workflow.shutdown()
