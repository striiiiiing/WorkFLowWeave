"""Ownership and durable-result contracts for Workflow Agent task adaptation."""

import asyncio
from copy import deepcopy

import pytest

from workflowweave.ai.errors import ModelError
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import AIConfig, ErrorInfo
from workflowweave.workflow.agent_tasks import execute_agent_task


class Agent:
    def __init__(self, *, block=None, outcome=None):
        self.block = block
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cleaned = asyncio.Event()
        self.created = {}
        self.requests = {}
        self.outcomes = {}
        self.cancelled = []
        self.calls = []
        self.outcome = outcome or {"status": "completed", "text": "first result"}

    async def _barrier(self, phase):
        if self.block == phase:
            self.entered.set()
            await self.release.wait()

    async def create_session(self, **options):
        self.calls.append(deepcopy(options))
        await self._barrier("create")
        operation = options["operation_id"]
        self.created.setdefault(operation, "agent-" + operation)
        return {"session_id": self.created[operation]}

    async def submit(self, session_id, text, *, request_id):
        await self._barrier("submit")
        key = session_id, request_id
        if key not in self.requests:
            turn_id = "turn-" + request_id
            self.requests[key] = turn_id
            self.outcomes[turn_id] = (
                self.outcome if isinstance(self.outcome, BaseException) else deepcopy(self.outcome)
            )
        return {"session_id": session_id, "turn_id": self.requests[key]}

    async def wait(self, turn_id):
        await self._barrier("wait")
        outcome = self.outcomes[turn_id]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def cancel(self, session_id):
        self.cancelled.append(session_id)
        await self._barrier("cancel")
        self.cleaned.set()


def invocation():
    return {
        "operation_id": "archive-operation",
        "workflow_session_id": "run",
        "workflow_task_id": "task",
        "ai_config": AIConfig(id="task-ai", provider="mock", models={"model": {}}),
        "model": "model",
        "workflow_result": "original input",
        "user_prompt": "analyze {input}",
        "tool_names": [],
    }


async def test_completed_task_keeps_the_accepted_turn_after_later_conversation_and_restart():
    agent = Agent()
    first = await execute_agent_task(agent, **invocation())
    assert first.status == "success"
    assert first.agent_session_id == "agent-archive-operation"
    assert agent.calls[0]["ai_config"].id == "task-ai"
    assert agent.calls[0]["tool_names"] == []
    agent.outcome = {"status": "completed", "text": "later conversation"}
    later = await agent.submit(first.agent_session_id, "continue", request_id="later")
    assert (await agent.wait(later["turn_id"]))["text"] == "later conversation"
    restored = Agent()
    restored.created, restored.requests, restored.outcomes = (
        agent.created, agent.requests, agent.outcomes,
    )
    replay = await execute_agent_task(restored, **invocation())
    assert replay == first
    assert len(restored.requests) == 2


@pytest.mark.parametrize("phase", ["create", "submit", "wait"])
async def test_parent_cancellation_waits_for_admission_and_cleans_the_agent(phase):
    agent = Agent(block=phase)
    task = asyncio.create_task(execute_agent_task(agent, **invocation()))
    await asyncio.wait_for(agent.entered.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    agent.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert agent.cancelled == ["agent-archive-operation"]
    assert agent.cleaned.is_set()


@pytest.mark.parametrize("phase", ["create", "submit", "wait"])
async def test_repeated_cancellation_cannot_abandon_admission_or_cleanup(phase):
    agent = Agent(block=phase)
    task = asyncio.create_task(execute_agent_task(agent, **invocation()))
    await asyncio.wait_for(agent.entered.wait(), 1)
    if phase == "wait":
        agent.block = "cancel"
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    agent.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert agent.cancelled == ["agent-archive-operation"]
    assert agent.cleaned.is_set()


async def test_repeated_cancellation_waits_until_agent_cleanup_finishes():
    agent = Agent(block="cancel")
    agent.outcome = asyncio.CancelledError()
    task = asyncio.create_task(execute_agent_task(agent, **invocation()))
    await asyncio.wait_for(agent.entered.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    agent.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert agent.cleaned.is_set()


async def test_independently_cancelled_agent_becomes_a_cancelled_task_result():
    agent = Agent(outcome=asyncio.CancelledError())
    result = await execute_agent_task(agent, **invocation())
    assert result.status == "cancelled"
    assert result.error.code == "agent_cancelled"
    assert agent.cancelled == [result.agent_session_id]
    assert not asyncio.current_task().cancelling()


@pytest.mark.parametrize("outcome, code, status", [
    (WorkFLowWeaveError("tool_failed", "工具拒绝", {"tool": "read"}), "tool_failed", "failed"),
    (WorkFLowWeaveError("ai_timeout", "模型超时"), "ai_timeout", "timeout"),
    ({"status": "failed", "error": {"code": "checkpoint_corrupt", "message": "损坏"}},
     "checkpoint_corrupt", "failed"),
    ({"status": "interrupted", "error": None}, "agent_interrupted", "failed"),
    (RuntimeError("private input must not escape"), "agent_failed", "failed"),
])
async def test_failures_preserve_structured_diagnostics_without_private_exception_text(
    outcome, code, status,
):
    result = await execute_agent_task(Agent(outcome=outcome), **invocation())
    assert result.status == status
    assert result.error.code == code
    assert result.agent_session_id == "agent-archive-operation"
    if isinstance(outcome, WorkFLowWeaveError):
        assert result.error == outcome.info
    if isinstance(outcome, RuntimeError):
        assert result.error.details == {"exception_type": "RuntimeError"}
        assert "private input" not in result.model_dump_json()


async def test_provider_error_keeps_the_already_redacted_report():
    error = ModelError("provider_unavailable", "上游失败", status_code=502)
    error.report = ErrorInfo(
        code=error.code, message="上游失败", details={"response_body": "diagnostic [REDACTED]"},
    )
    result = await execute_agent_task(Agent(outcome=error), **invocation())
    assert result.error == error.report


async def test_failed_cleanup_is_visible_instead_of_becoming_a_successful_cancel():
    class FailingCleanup(Agent):
        async def cancel(self, session_id):
            raise WorkFLowWeaveError("agent_cleanup_failed", "工具关闭失败")

    with pytest.raises(WorkFLowWeaveError, match="工具关闭失败"):
        await execute_agent_task(FailingCleanup(outcome=asyncio.CancelledError()), **invocation())
