"""Workflow and Agent graphs share real SQLite stores and frozen turn results."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.interaction.fastapi.agent import create_agent_service
from workflowweave.models import AIConfig, FanInConfig
from workflowweave.workflow.execution.runner import WorkflowRunner
from workflowweave.workflow.storage.facts import SessionStore
from tests.agent.helpers import ScriptedModel
from tests.workflow.helpers import AI, Channel, Collector, snapshot


class FailingModel(ScriptedModel):
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        raise WorkFLowWeaveError("tool_failed", "工具拒绝请求", {"tool": "read"})


async def test_mixed_llm_agent_tasks_and_agent_summary_keep_separate_configuration(tmp_path):
    models = {}

    def provider(session):
        model = models.setdefault(session.session_id, ScriptedModel(responses=[
            AIMessage(content="agent:" + session.workflow_task_id),
        ]))
        return model

    agent = create_agent_service(tmp_path / "workspace", tmp_path / "agent", model_provider=provider)
    workflow = WorkflowRunner(Collector(), AI(), Channel(), agent_service=agent,
                               database=tmp_path / "workflow.sqlite3")
    snap = snapshot(tasks=("llm", "research", "review"), channels=False)
    snap.ai["summary"] = AIConfig(id="summary", provider="mock", system_prompt="summary system",
                                  models={"summary-model": {}})
    snap.workflow.system_prompt = "analysis system"
    for task, tools in zip(snap.workflow.analyses[1:], (["read"], []), strict=True):
        task.agent_mode = True
        task.agent_tools = tools
        task.user_prompt = "分析提供的来源"
    snap.workflow.fan_in = FanInConfig(
        ai="summary", model="summary-model", system_prompt="summary system", input_prompt="summary {input}", user_prompt="汇总结果", reuse_from=None,
        agent_mode=True, agent_tools=[],
    )
    try:
        result = await workflow.wait(await workflow.trigger(snap, session_id="run"))
        assert result.status == "completed"
        assert [call[0] for call in workflow.ai_service.calls] == ["llm"]
        sessions = {session.workflow_task_id: session for session in agent.sessions.values()}
        assert set(sessions) == {"research", "review", "final"}
        for key, tools in (("research", ["read"]), ("review", []), ("final", [])):
            session = sessions[key]
            model = models[session.session_id]
            assert [tool.name for tool in model.bound_tools] == tools
            assert session.model == ("summary-model" if key == "final" else "offline")
            system = "summary system" if key == "final" else "analysis system"
            assert system in model.seen[0][0].content
            humans = [message.content for message in model.seen[0] if isinstance(message, HumanMessage)]
            assert humans[0].startswith("summary " if key == "final" else key + ": ")
            assert session.workflow_session_id == "run"
            assert agent.repository.bindings.read(session.session_id) == {"servers": {}, "sources": []}
        assert "agent:research" in sessions["final"].workflow_input
        assert result.outputs == {"final": "agent:final"}
        assert result.aggregate.agent_session_id == sessions["final"].session_id
        version = (await workflow.get_session("run")).version
        phase = await workflow.session_view.get_phase_content("run", "analyze", version=version)
        assert all(item["agent_session_id"] for item in phase.content["analyses"] if item["task_id"] != "llm")
    finally:
        await workflow.shutdown()
        await agent.close()


@pytest.mark.parametrize("policy, partial, status", [
    ("stop", True, "failed"), ("continue", False, "failed"), ("continue", True, "partial"),
])
async def test_agent_failure_obeys_workflow_partial_delivery_policy(tmp_path, policy, partial, status):
    agent = create_agent_service(
        tmp_path / "workspace", tmp_path / "agent",
        model_provider=lambda _: FailingModel(responses=[]),
    )
    workflow = WorkflowRunner(Collector(), AI(), Channel(), agent_service=agent,
                               database=tmp_path / "workflow.sqlite3")
    snap = snapshot(analysis_failure=policy, send_partial=partial)
    snap.workflow.analyses[1].agent_mode = True
    snap.workflow.analyses[1].agent_tools = []
    snap.workflow.analyses[1].user_prompt = "分析来源"
    try:
        result = await workflow.wait(await workflow.trigger(snap, session_id="run"))
        assert result.status == status
        failed = result.analyses[1]
        assert failed.status == "failed" and failed.error.code == "tool_failed"
        assert failed.error.details == {"tool": "read"}
        assert failed.agent_session_id
        assert len(workflow.channel_manager.calls) == (2 if status == "partial" else 0)
    finally:
        await workflow.shutdown()
        await agent.close()


async def test_retry_creates_new_agent_and_reuses_successful_workflow_branch(tmp_path):
    models = {}

    def provider(session):
        if session.session_id not in models:
            models[session.session_id] = (FailingModel(responses=[]) if not models else
                                          ScriptedModel(responses=[AIMessage(content="retried")]))
        return models[session.session_id]

    collector, ai = Collector(), AI()
    agent = create_agent_service(tmp_path / "workspace", tmp_path / "agent", model_provider=provider)
    workflow = WorkflowRunner(collector, ai, Channel(), agent_service=agent,
                               database=tmp_path / "workflow.sqlite3")
    snap = snapshot(channels=False, analysis_failure="stop")
    snap.workflow.analyses[1].agent_mode = True
    snap.workflow.analyses[1].agent_tools = []
    snap.workflow.analyses[1].user_prompt = "分析来源"
    try:
        first = await workflow.wait(await workflow.trigger(snap, session_id="run"))
        assert first.status == "failed"
        original_id = first.analyses[1].agent_session_id
        await workflow.resume("run", stage="analyze")
        retried = await workflow.wait("run")
        assert retried.status == "completed"
        assert retried.analyses[1].agent_session_id != original_id
        assert len(agent.sessions) == 2
        assert [call[0] for call in ai.calls] == ["first", "first"]
        assert collector.calls == ["source"]
    finally:
        await workflow.shutdown()
        await agent.close()


async def test_later_agent_conversation_does_not_change_parent_workflow_archive(tmp_path):
    model = ScriptedModel(responses=[AIMessage(content="task result"), AIMessage(content="later")])
    agent = create_agent_service(tmp_path / "workspace", tmp_path / "agent", model_provider=lambda _: model)
    workflow = WorkflowRunner(Collector(), AI(), Channel(), agent_service=agent,
                               database=tmp_path / "workflow.sqlite3")
    snap = snapshot(tasks=("first",), channels=False)
    snap.workflow.analyses[0].agent_mode = True
    snap.workflow.analyses[0].agent_tools = []
    snap.workflow.analyses[0].user_prompt = "分析来源"
    try:
        result = await workflow.wait(await workflow.trigger(snap, session_id="run"))
        sid = result.analyses[0].agent_session_id
        before = await workflow.get_session("run")
        accepted = await agent.submit(sid, "followup", request_id="later")
        assert (await agent.wait(accepted["turn_id"]))["text"] == "later"
        after = await workflow.get_session("run")
        assert after.version == before.version
        phase = await workflow.session_view.get_phase_content("run", "aggregate", version=after.version)
        assert phase.content["outputs"] == result.outputs == {"first": "task result"}
    finally:
        await workflow.shutdown()
        await agent.close()


async def test_restart_recovers_completed_agent_turn_when_parent_archive_was_not_committed(tmp_path):
    class FailAnalysisWrite(SessionStore):
        def write(self, session_id, key, **options):
            if key.startswith("analyze:item:first:epoch:"):
                raise RuntimeError("process interrupted before parent archive")
            return super().write(session_id, key, **options)

    model = ScriptedModel(responses=[AIMessage(content="only once")])
    agent_paths = tmp_path / "workspace", tmp_path / "agent"
    database = tmp_path / "workflow.sqlite3"
    store = FailAnalysisWrite(database)
    agent = create_agent_service(*agent_paths, model_provider=lambda _: model)
    workflow = WorkflowRunner(Collector(), AI(), Channel(), agent_service=agent, session_store=store)
    snap = snapshot(tasks=("first",), channels=False)
    snap.workflow.analyses[0].agent_mode = True
    snap.workflow.analyses[0].agent_tools = []
    snap.workflow.analyses[0].user_prompt = "分析来源"
    try:
        await workflow.trigger(snap, session_id="run")
        with pytest.raises(RuntimeError, match="process interrupted before parent archive"):
            await workflow.wait("run")
        original_agent_id = next(iter(agent.sessions))
        assert len(model.seen) == 1
    finally:
        await workflow.shutdown()
        await agent.close()
        store.close()
    restored_agent = create_agent_service(*agent_paths, model_provider=lambda _: model)
    restored = WorkflowRunner(Collector(), AI(), Channel(), agent_service=restored_agent, database=database)
    try:
        await restored.resume("run")
        result = await restored.wait("run")
        assert result.status == "completed"
        assert result.outputs == {"first": "only once"}
        assert result.analyses[0].agent_session_id == original_agent_id
        assert len(model.seen) == 1
        assert not restored.collector_manager.calls
        assert not restored.ai_service.calls
    finally:
        await restored.shutdown()
        await restored_agent.close()


@pytest.mark.parametrize("agent_mode", [False, True])
async def test_source_free_workflow_runs_task_and_own_summary(tmp_path, agent_mode):
    def provider(session):
        return ScriptedModel(responses=[AIMessage(content="agent:" + session.workflow_task_id)])

    agent = create_agent_service(tmp_path / "workspace", tmp_path / "agent", model_provider=provider)
    workflow = WorkflowRunner(Collector(), AI(), Channel(), agent_service=agent,
                              database=tmp_path / "workflow.sqlite3")
    snap = snapshot(tasks=("first",), channels=False)
    snap.workflow.sources, snap.sources = [], {}
    task = snap.workflow.analyses[0]
    task.agent_mode, task.agent_tools, task.user_prompt = agent_mode, [], "分析问题"
    snap.workflow.fan_in = FanInConfig(
        agent_mode=agent_mode, agent_tools=[], user_prompt="汇总分析结果",
    )
    try:
        result = await workflow.wait(await workflow.trigger(snap))
        assert result.status == "completed"
        assert result.collection == [] and result.shared_input == ""
        assert not workflow.collector_manager.calls
        if agent_mode:
            assert result.outputs == {"final": "agent:final"}
            assert not workflow.ai_service.calls
            assert result.aggregate.agent_session_id
        else:
            assert result.outputs == {"final": "final(\n\nfirst())"}
            assert [call[0] for call in workflow.ai_service.calls] == ["first", "final"]
    finally:
        await workflow.shutdown()
        await agent.close()
