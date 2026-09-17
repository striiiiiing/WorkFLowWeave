"""Admission and cleanup races at the application lifecycle boundary."""

import asyncio

import pytest
from test_workflow_recovery import AI, Channel, Collector, snapshot

from logagent.errors import LogAgentError
from logagent.workflow import WorkflowService


async def test_pause_waits_for_admitted_trigger_to_finish_archiving(tmp_path):
    ai = AI(block="first")
    workflow = WorkflowService(Collector(), ai, Channel(), database=tmp_path / "runs.sqlite3")
    entered, release = asyncio.Event(), asyncio.Event()
    original = workflow._snapshot

    async def delayed(value):
        entered.set()
        await release.wait()
        return await original(value)

    workflow._snapshot = delayed
    try:
        trigger = asyncio.create_task(workflow.trigger(snapshot(), session_id="admitted"))
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
    workflow = WorkflowService(Collector(), AI(), Channel(), database=tmp_path / "runs.sqlite3")
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
