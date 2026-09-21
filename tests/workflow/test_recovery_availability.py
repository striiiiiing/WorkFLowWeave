"""The read-only recovery query must agree with the actual material check."""
import pytest

from logagent.errors import LogAgentError
from logagent.models import BackupPolicy
from tests.workflow.helpers import AI, snapshot
from tests.workflow.test_workflow_recovery import close, run, service


async def test_query_and_recover_agree_on_missing_material_without_changing_history(tmp_path):
    workflow, store, _, _, _ = service(tmp_path / "runs.sqlite3")
    try:
        await run(workflow, snapshot(backup=BackupPolicy(snapshot=False)))
        before = await workflow.history("run")
        eligibility = await workflow.recovery_availability("run")
        assert not eligibility.available
        assert eligibility.reason.code == "recovery_unavailable"
        assert await workflow.history("run") == before
        with pytest.raises(LogAgentError) as caught:
            await workflow.recover("run")
        assert caught.value.info == eligibility.reason
    finally:
        await close(workflow, store)


async def test_query_checks_active_run_and_allows_cancelled_run_with_material(tmp_path):
    ai = AI(block="second")
    workflow, store, collector, _, channel = service(tmp_path / "runs.sqlite3", ai=ai)
    try:
        await workflow.trigger(snapshot(analysis_concurrency=1), session_id="run")
        await ai.started.wait()
        assert (await workflow.recovery_availability("run")).reason.code == "session_active"
        await workflow.cancel("run")
        await workflow.wait("run")
        eligibility = await workflow.recovery_availability("run")
        assert eligibility.available and eligibility.reason is None
        before = len(collector.calls), len(ai.calls), len(channel.calls)
        assert (await workflow.recovery_availability("run")).available
        assert before == (len(collector.calls), len(ai.calls), len(channel.calls))
        ai.block = None
        await workflow.recover("run")
        assert (await workflow.wait("run")).status == "completed"
    finally:
        await close(workflow, store)
