"""Dependency and ownership rules of the Agent module redesign."""

import ast
from dataclasses import fields
from pathlib import Path

from logagent.agent.contracts import SessionView

SOURCE = Path(__file__).parents[2] / "src" / "logagent"


def imports(path):
    tree = ast.parse(path.read_text())
    return [
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
        if not isinstance(node, ast.ImportFrom) or node.level == 0
    ]


def test_session_projection_has_no_execution_or_storage_handles():
    assert not {"task", "lock", "log", "pending_appends", "compact_events"} & {
        field.name for field in fields(SessionView)
    }


def test_shared_storage_primitives_have_no_domain_dependencies():
    for path in (SOURCE / "storage_primitives").rglob("*.py"):
        for name in imports(path):
            assert not name.startswith((
                "logagent.agent", "logagent.workflow", "langgraph", "fastapi", "sqlmodel",
            )), (path, name)


def test_runtime_depends_on_ports_and_values_not_transport_or_integrations():
    for path in (SOURCE / "agent" / "runtime").rglob("*.py"):
        for name in imports(path):
            assert not name.startswith((
                "logagent.interaction", "logagent.channel", "logagent.lifecycle",
                "logagent.agent.integrations",
            )), (path, name)


def test_facade_does_not_construct_runtime_or_external_dependencies():
    tree = ast.parse((SOURCE / "agent" / "service.py").read_text())
    forbidden = {
        "WorkspaceBackend", "ArtifactStore", "AsyncSqliteSaver", "ToolScheduler",
        "StateGraph", "ChannelManager", "MCPRuntime", "AIService", "PluginRegistry",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden


def test_internal_flat_modules_and_command_reexports_are_removed():
    retired = (
        "artifacts", "binding", "channel", "context", "events", "gateway", "graph",
        "io", "process", "process_supervisor", "sandbox", "scheduling", "workspace",
    )
    for name in retired:
        assert not (SOURCE / "agent" / f"{name}.py").exists()
    assert not (SOURCE / "agent" / "builtin").exists()
    channel_tree = ast.parse((SOURCE / "channel" / "agent.py").read_text())
    assert any(isinstance(node, ast.ClassDef) and node.name == "AgentChannelProcessor"
               for node in channel_tree.body)
    assert not any(isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
    ) for node in channel_tree.body)
