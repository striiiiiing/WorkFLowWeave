import json
from pathlib import Path

from workflowweave.models import AIConfig, MCPServerConfig, SourceConfig, WorkflowDefinition

ROOT = Path(__file__).parents[2] / "examples" / "workflows" / "business-scenarios"


def load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_business_resources_match_project_schema():
    AIConfig.model_validate(load("ai.json"))
    for path in ROOT.glob("*-mcp-server.json"):
        MCPServerConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    for path in ROOT.glob("*-source.json"):
        SourceConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    for name in ("news-lossy-compression.json", "stock-fanout-fanin.json", "github-issue-task-split.json"):
        WorkflowDefinition.model_validate(load(name))


def test_news_chain_only_passes_compression_to_stronger_model():
    workflow = WorkflowDefinition.model_validate(load("news-lossy-compression.json"))
    assert workflow.fan_in is not None
    assert workflow.fan_in.order == ["compress"]
    assert workflow.fan_in.reuse_from is None
    assert workflow.fan_in.single_task_optimization is False
    assert "$input" not in workflow.fan_in.order


def test_stock_has_three_tool_using_directions_and_strong_fanin():
    workflow = WorkflowDefinition.model_validate(load("stock-fanout-fanin.json"))
    assert [task.id for task in workflow.analyses] == [
        "operations_finance", "valuation_market", "risk_events"
    ]
    assert all(task.agent_mode and task.agent_tools == ["mcp", "read"] for task in workflow.analyses)
    assert workflow.fan_in is not None
    assert workflow.fan_in.model == "gpt-6.1-sol"


def test_issue_assigns_business_judgment_before_root_cause_without_fanin():
    workflow = WorkflowDefinition.model_validate(load("github-issue-task-split.json"))
    assert workflow.analyses[0].model == "gpt-6.1-sol"
    assert workflow.analyses[1].agent_mode is True
    assert workflow.analyses[1].model == "gpt-6-luna"
    assert workflow.fan_in is None


def test_examples_reference_only_qq_and_no_inline_secrets():
    for name in ("news-lossy-compression.json", "stock-fanout-fanin.json", "github-issue-task-split.json"):
        workflow = load(name)
        assert workflow["channels"] == ["business_qq"]
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "client_secret" not in text and "ciphertext" not in text
