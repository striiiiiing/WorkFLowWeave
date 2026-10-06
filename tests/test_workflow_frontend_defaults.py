"""Workflow creation defaults shared by the resource API and web editor."""

import pytest
from pydantic import ValidationError

from workflowweave.models import AnalysisTask, FanInConfig, WorkflowDefinition


def test_counts_default_on_but_explicit_saved_false_is_preserved():
    payload = {
        "id": "default_counts",
        "sources": ["source"],
        "analyses": [{"user_prompt": "analyze input", "id": "task", "ai": "ai", "model": "model"}],
    }
    assert WorkflowDefinition.model_validate(payload).include_counts is True
    assert WorkflowDefinition.model_validate({**payload, "include_counts": False}).include_counts is False


def test_new_api_rejects_legacy_prompts():
    payload = {"id": "workflow", "sources": ["source"],
               "analyses": [{"id": "task", "ai": "ai", "model": "model", "prompt": "old"}]}
    with pytest.raises(ValidationError, match="prompt"):
        WorkflowDefinition.model_validate(payload)
    with pytest.raises(ValidationError, match="prompt"):
        FanInConfig.model_validate({"prompt": "old"})


def test_fanin_model_source_must_be_unambiguous():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        FanInConfig(user_prompt="summarize results", ai="ai", model="model")
    assert FanInConfig(user_prompt="summarize results", ai="ai", model="model", reuse_from=None).reuse_from is None


@pytest.mark.parametrize("agent_mode", [False, True])
@pytest.mark.parametrize("field", ["user_prompt", "input_prompt"])
@pytest.mark.parametrize("blank", ["", " \n\t"])
def test_new_tasks_reject_blank_human_prompts(agent_mode, field, blank):
    task = dict(id="task", ai="ai", model="model", agent_mode=agent_mode,
                user_prompt="analyze", input_prompt="{input}")
    with pytest.raises(ValidationError, match=field):
        AnalysisTask.model_validate({**task, field: blank})
    fan = dict(agent_mode=agent_mode, user_prompt="summarize", input_prompt="{input}")
    with pytest.raises(ValidationError, match=field):
        FanInConfig.model_validate({**fan, field: blank})


def test_workflow_shared_input_template_is_required_and_blank_system_is_an_override():
    payload = {"id": "workflow", "system_prompt": "shared system", "input_prompt": "{input}",
               "analyses": [{"id": "task", "ai": "ai", "model": "model",
                             "system_prompt": "", "user_prompt": "analyze"}]}
    workflow = WorkflowDefinition.model_validate(payload)
    assert workflow.analyses[0].system_prompt == ""
    assert workflow.analyses[0].input_prompt is None
    with pytest.raises(ValidationError, match="input_prompt"):
        WorkflowDefinition.model_validate({**payload, "input_prompt": "  "})


@pytest.mark.parametrize("agent_mode", [False, True])
def test_summary_default_input_order_is_explicitly_overridable(agent_mode):
    task = AnalysisTask(id="task", ai="ai", model="model", user_prompt="analyze")
    fan = FanInConfig(agent_mode=agent_mode, user_prompt="summarize")
    assert fan.ordered_inputs([task]) == ["$input", "task"]
    fan.order = ["task"]
    assert fan.ordered_inputs([task]) == ["task"]


def test_historical_empty_prompts_are_not_accepted_by_new_api():
    payload = {"id": "workflow", "input_prompt": "",
               "analyses": [{"id": "task", "ai": "ai", "model": "model", "user_prompt": ""}],
               "fan_in": {"user_prompt": "", "input_prompt": ""}}
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(payload)
    historical = WorkflowDefinition.model_validate(payload, context={"historical_snapshot": True})
    assert historical.analyses[0].user_prompt == ""
    assert historical.fan_in.single_task_optimization is False


def test_plain_text_fanin_does_not_require_model_prompts():
    assert FanInConfig(reuse_from=None).user_prompt == ""
