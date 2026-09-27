"""Workflow creation defaults shared by the resource API and web editor."""

import pytest
from pydantic import ValidationError

from logagent.models import FanInConfig, WorkflowDefinition


def test_counts_default_on_but_explicit_saved_false_is_preserved():
    payload = {
        "id": "default_counts",
        "sources": ["source"],
        "analyses": [{"id": "task", "ai": "ai", "model": "model"}],
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
        FanInConfig(ai="ai", model="model")
    assert FanInConfig(ai="ai", model="model", reuse_from=None).reuse_from is None
