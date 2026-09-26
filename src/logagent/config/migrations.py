"""Versioned migrations for locally persisted resource documents."""

from copy import deepcopy
from typing import Any

from logagent.errors import LogAgentError

RESOURCE_FORMAT_VERSION = 2


def _object(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise LogAgentError("invalid_config", f"旧资源 {name} 必须是对象")
    return value


def _input_prompt(value: Any) -> str:
    if not isinstance(value, str):
        raise LogAgentError("invalid_config", "旧 prompt 必须是字符串")
    return value if "{input}" in value else f"{value}\n\n{{input}}"


def _migrate_workflow_prompts(workflow: dict, ai: dict) -> None:
    analyses = workflow.get("analyses")
    if not isinstance(analyses, list):
        raise LogAgentError("invalid_config", "旧 Workflow analyses 必须是列表")
    workflow["system_prompt"] = ""
    workflow["input_prompt"] = "{input}"
    for task in analyses:
        task = _object(task, "analysis")
        config = _object(ai.get(task.get("ai")), "analysis AI")
        task["system_prompt"] = config.get("system_prompt", "")
        task["input_prompt"] = _input_prompt(task.pop("prompt", "{input}"))
        task["user_prompt"] = ""
    fan_in = workflow.get("fan_in")
    if fan_in is not None:
        fan_in = _object(fan_in, "fan_in")
        if fan_in.get("ai") is not None:
            config = _object(ai.get(fan_in["ai"]), "fan_in AI")
            fan_in["system_prompt"] = config.get("system_prompt", "")
        fan_in["input_prompt"] = _input_prompt(fan_in.pop("prompt", "{input}"))
        fan_in["user_prompt"] = ""
        fan_in["reuse_from"] = None
        if fan_in.get("order", []) == []:
            fan_in["order"] = [task.get("id") for task in analyses]


def _migrate_v1_prompts(data: dict) -> dict:
    migrated = deepcopy(data)
    ai = _object(migrated.get("ai"), "ai")
    workflows = _object(migrated.get("workflows"), "workflows")
    for value in workflows.values():
        _migrate_workflow_prompts(_object(value, "workflow"), ai)
    migrated["format_version"] = RESOURCE_FORMAT_VERSION
    return migrated


_MIGRATIONS = {1: _migrate_v1_prompts}


def migrate_resources(data: Any) -> tuple[Any, bool]:
    """Upgrade only stored versions; API payloads use current strict models."""
    if not isinstance(data, dict):
        return data, False
    changed = False
    version = data.get("format_version")
    while type(version) is int and version in _MIGRATIONS:
        data = _MIGRATIONS[version](data)
        changed = True
        version = data["format_version"]
    return data, changed


def migrate_legacy_snapshot(data: Any) -> Any:
    """Read old session archives without accepting legacy fields in new API requests."""
    if not isinstance(data, dict) or not isinstance(data.get("workflow"), dict):
        return data
    workflow = data["workflow"]
    analyses = workflow.get("analyses")
    if not isinstance(analyses, list):
        return data
    fan_in = workflow.get("fan_in")
    has_legacy_prompt = any(isinstance(task, dict) and "prompt" in task for task in analyses)
    has_legacy_prompt |= isinstance(fan_in, dict) and "prompt" in fan_in
    if not has_legacy_prompt:
        return data
    migrated = deepcopy(data)
    _migrate_workflow_prompts(
        _object(migrated["workflow"], "workflow"), _object(migrated.get("ai"), "ai"),
    )
    return migrated
