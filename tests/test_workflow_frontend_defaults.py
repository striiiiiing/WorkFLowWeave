"""Workflow creation defaults shared by the resource API and web editor."""

from logagent.models import WorkflowDefinition


def test_counts_default_on_but_explicit_saved_false_is_preserved():
    payload = {
        "id": "default_counts",
        "sources": ["source"],
        "analyses": [{"id": "task", "ai": "ai", "model": "model", "prompt": "{input}"}],
    }
    assert WorkflowDefinition.model_validate(payload).include_counts is True
    assert WorkflowDefinition.model_validate({**payload, "include_counts": False}).include_counts is False
