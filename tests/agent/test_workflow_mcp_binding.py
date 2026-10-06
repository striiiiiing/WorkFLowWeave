"""Workflow-bound Agent MCP isolation contracts."""

from __future__ import annotations

import pytest

from workflowweave.agent.integrations.workflow import resolve_mcp_binding
from workflowweave.errors import WorkFLowWeaveError


def test_binding_returns_exact_requested_mcp_set_in_stable_order():
    binding = resolve_mcp_binding(
        agent_id="workflow-agent",
        requested_mcp_ids=["filesystem", "browser"],
        enabled_mcp_ids={"browser", "filesystem", "calendar"},
        allowed_mcp_ids={"filesystem", "browser"},
    )

    assert binding.agent_id == "workflow-agent"
    assert binding.mcp_ids == ("filesystem", "browser")


@pytest.mark.parametrize(
    "requested, enabled, allowed",
    [
        (["filesystem", "missing"], {"filesystem"}, {"filesystem", "missing"}),
        (["filesystem", "browser"], {"filesystem"}, {"filesystem", "browser"}),
        (["filesystem", "calendar"], {"filesystem", "calendar"}, {"filesystem"}),
    ],
)
def test_binding_rejects_missing_disabled_or_unauthorized_mcp(requested, enabled, allowed):
    with pytest.raises(WorkFLowWeaveError, match="MCP"):
        resolve_mcp_binding(
            agent_id="workflow-agent",
            requested_mcp_ids=requested,
            enabled_mcp_ids=enabled,
            allowed_mcp_ids=allowed,
        )


def test_binding_does_not_fallback_to_global_mcp_set():
    with pytest.raises(WorkFLowWeaveError, match="MCP"):
        resolve_mcp_binding(
            agent_id="workflow-agent",
            requested_mcp_ids=[],
            enabled_mcp_ids={"global-default"},
            allowed_mcp_ids=set(),
        )
