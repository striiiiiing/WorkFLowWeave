"""Model-visible summary prefixes through real AI/Agent services and SQLite."""

import pytest
from langchain_core.messages import AIMessage

from logagent.agent.service import AgentService
from logagent.ai import AIService
from logagent.models import AIConfig, FanInConfig, WorkflowSnapshot, copy_model
from logagent.workflow.execution.runner import WorkflowRunner
from tests.agent.helpers import ScriptedModel
from tests.workflow.helpers import Channel, Collector, snapshot
from tests.workflow_ai_helpers import TestChannelFactory


def contents(messages):
    return [(message.type, message.content) for message in messages]


class RecordingFactory(TestChannelFactory):
    def __init__(self):
        super().__init__()
        self.models = {}

    def create_model(self, config, *, model, **kwargs):
        return self.models.setdefault((config.id, model), ScriptedModel(
            responses=[AIMessage(content="answer " + str(index)) for index in range(4)],
        ))


def definition(tasks=("first",), *, enabled=True, selection="reuse"):
    snap = snapshot(tasks=tasks, channels=False, system_prompt="shared {input}",
                    input_prompt="shared body: {input}")
    for task in snap.workflow.analyses:
        task.input_prompt = None
        task.user_prompt = task.id + " instruction {input}"
    snap.workflow.analyses[0].system_prompt = "task system {input}"
    fan = FanInConfig(
        order=list(tasks), system_prompt="summary system", input_prompt="results: {input}",
        user_prompt="summary instruction {input}",
    )
    if not enabled:
        fan.single_task_optimization = False
    if selection != "reuse":
        fan.reuse_from = None
        fan.ai = "other" if selection == "other_provider" else "ai"
        fan.model = "other" if selection == "other_model" else "offline"
        if selection == "other_provider":
            snap.ai["other"] = AIConfig(id="other", provider="mock", models={"offline": {}})
        elif selection == "other_model":
            snap.ai["ai"].models["other"] = {}
    snap.workflow.fan_in = fan
    return snap


@pytest.mark.parametrize("tasks,enabled,selection,optimized", [
    (("first",), True, "reuse", True),
    (("first",), True, "explicit", True),
    (("first",), False, "reuse", False),
    (("first",), True, "other_model", False),
    (("first",), True, "other_provider", False),
    (("first", "second"), True, "reuse", False),
])
async def test_summary_messages_and_optimization_conditions(
    tmp_path, tasks, enabled, selection, optimized,
):
    factory = RecordingFactory()
    ai = AIService(channel_factories={"mock": factory})
    workflow = WorkflowRunner(Collector(), ai, Channel(), database=tmp_path / "runs.sqlite")
    snap = definition(tasks, enabled=enabled, selection=selection)
    before = copy_model(snap)
    try:
        result = await workflow.wait(await workflow.trigger(snap))
        assert result.status == "completed"
        analysis = factory.models["ai", "offline"].seen[0]
        assert contents(analysis) == [
            ("system", "task system {input}"),
            ("human", "shared body: " + result.shared_input),
            ("human", "first instruction {input}"),
        ]
        fan = snap.workflow.fan_in
        summary = factory.models[fan.ai or "ai", fan.model or "offline"].seen[-1]
        if optimized:
            assert contents(summary) == [
                *contents(analysis), ("ai", result.analyses[0].text),
                ("human", "summary instruction {input}"),
            ]
        else:
            previous = fan.separator.join(item.text for item in result.analyses)
            assert contents(summary) == [
                ("system", "summary system"), ("human", "results: " + previous),
                ("human", "summary instruction {input}"),
            ]
        assert sum(len(model.seen) for model in factory.models.values()) == len(tasks) + 1
        assert snap == before
    finally:
        await workflow.shutdown()
        await ai.close()


@pytest.mark.parametrize("analysis_agent", [False, True])
@pytest.mark.parametrize("override", [False, True])
async def test_single_same_model_agent_summary_ignores_enabled_optimization(
    tmp_path, analysis_agent, override,
):
    models = {}

    def provider(session):
        model = ScriptedModel(responses=[AIMessage(content="answer " + session.workflow_task_id)])
        models[session.workflow_task_id] = model
        return model

    agent = AgentService(tmp_path / "workspace", tmp_path / "agent", model_provider=provider)
    factory = RecordingFactory()
    ai = AIService(channel_factories={"mock": factory})
    workflow = WorkflowRunner(Collector(), ai, Channel(), agent_service=agent,
                              database=tmp_path / "runs.sqlite")
    snap = definition()
    task = snap.workflow.analyses[0]
    task.agent_mode, task.agent_tools = analysis_agent, []
    fan = snap.workflow.fan_in
    fan.agent_mode, fan.agent_tools = True, []
    fan.system_prompt = "summary rules" if override else None
    fan.input_prompt = "summary input: {input}" if override else None
    assert fan.single_task_optimization is True
    try:
        result = await workflow.wait(await workflow.trigger(snap, session_id="run"))
        assert result.status == "completed"
        summary = models["final"].seen[0]
        assert [message.type for message in summary] == ["system", "human", "human"]
        assert summary[0].content.endswith("summary rules" if override else "shared {input}")
        assert "task system" not in summary[0].content
        prefix = "summary input: " if override else "shared body: "
        assert contents(summary)[1:] == [
            ("human", prefix + result.analyses[0].text),
            ("human", "summary instruction {input}"),
        ]
        assert result.shared_input not in summary[1].content
    finally:
        await workflow.shutdown()
        await agent.close()
        await ai.close()


@pytest.mark.parametrize("historical", [False, True])
async def test_aggregate_redo_preserves_saved_prompt_behavior(tmp_path, monkeypatch, historical):
    class FailSummary(ScriptedModel):
        async def _agenerate(self, messages, **kwargs):
            if len(self.seen) == 1:
                raise RuntimeError("summary unavailable")
            return await super()._agenerate(messages, **kwargs)

    class FailingFactory(RecordingFactory):
        def create_model(self, config, *, model, **kwargs):
            return self.models.setdefault((config.id, model), FailSummary(
                responses=[AIMessage(content="original analysis")],
            ))

    database = tmp_path / "runs.sqlite"
    factory = FailingFactory()
    ai = AIService(channel_factories={"mock": factory})
    workflow = WorkflowRunner(Collector(), ai, Channel(), database=database)
    snap = definition()
    if historical:
        snap.workflow.fan_in.single_task_optimization = False
        dump = WorkflowSnapshot.model_dump

        def legacy_dump(self, **kwargs):
            data = dump(self, **kwargs)
            if data["workflow"]["fan_in"]:
                data["workflow"]["fan_in"].pop("single_task_optimization", None)
            return data

        monkeypatch.setattr(WorkflowSnapshot, "model_dump", legacy_dump)
    snap.ai["ai"].retries = 0
    try:
        result = await workflow.wait(await workflow.trigger(snap, session_id="run"))
        assert result.status == "failed"
        original = contents(factory.models["ai", "offline"].seen[0])
        stored = workflow.session_store.entry("run", "snapshot")["body"]["snapshot"]
        assert ("single_task_optimization" in stored["workflow"]["fan_in"]) != historical
    finally:
        await workflow.shutdown()
        await ai.close()
    monkeypatch.undo()
    restored_factory = RecordingFactory()
    restored_ai = AIService(channel_factories={"mock": restored_factory})
    restored = WorkflowRunner(Collector(), restored_ai, Channel(), database=database)
    try:
        await restored.resume("run", stage="aggregate")
        result = await restored.wait("run")
        assert result.status == "completed"
        assert not restored.collector_manager.calls
        summary = contents(restored_factory.models["ai", "offline"].seen[0])
        expected = [
            ("system", "summary system"), ("human", "results: original analysis"),
            ("human", "summary instruction {input}"),
        ] if historical else [
            *original, ("ai", "original analysis"), ("human", "summary instruction {input}"),
        ]
        assert summary == expected
        assert restored.session_store.entry("run", "snapshot")["body"]["snapshot"] == stored
    finally:
        await restored.shutdown()
        await restored_ai.close()


def test_old_checkpoints_do_not_enable_an_optimization_they_did_not_save():
    data = definition().model_dump(mode="json")
    data["workflow"]["fan_in"].pop("single_task_optimization")
    assert WorkflowSnapshot.model_validate(data).workflow.fan_in.single_task_optimization is True
    assert WorkflowSnapshot.model_validate(
        data, context={"historical_snapshot": True},
    ).workflow.fan_in.single_task_optimization is False
    assert "single_task_optimization" not in data["workflow"]["fan_in"]
