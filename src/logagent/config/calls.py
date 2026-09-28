"""Invocation overlays shared by workflows and interactive agents."""

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

from logagent.config.normalize import normalize_options
from logagent.errors import LogAgentError
from logagent.models import (
    ChannelConfig,
    ChannelOverride,
    SetterTemplate,
    SourceConfig,
    SourceOverride,
    copy_model,
)
from logagent.schema import validate_workflow_options


def select_source_call(
    source: SourceConfig | None, override: SourceOverride | None = None,
) -> SourceConfig:
    """Select a workflow's detached source or its shared source."""
    if override is None or override.source is None:
        if source is None:
            raise LogAgentError("invalid_reference", "Workflow 引用的数据源不存在")
        return source
    if source is not None and override.source.id != source.id:
        raise LogAgentError("invalid_reference", "脱离的数据源快照与工作流绑定不匹配")
    return override.source


def resolve_source_call(
    source: SourceConfig | None, templates: Mapping[str, SetterTemplate],
    override: SourceOverride | None = None,
) -> SourceConfig:
    """Resolve call arguments and local limits once, before execution."""
    source = copy_model(select_source_call(source, override))
    if override is None:
        return source
    if override.arguments is not None:
        if source.call.kind != "mcp":
            raise LogAgentError("invalid_config", "arguments 覆盖只适用于 MCP 来源")
        source.call.arguments = {**source.call.arguments, **deepcopy(override.arguments)}
    source.limits = source.limits.model_copy(update={
        key: value for key, value in override.limits.model_dump().items() if value is not None
    })
    return source


def resolve_channel_call(
    channel: ChannelConfig, override: ChannelOverride | None = None,
) -> ChannelConfig:
    channel = copy_model(channel)
    if override is not None:
        channel.options = {**channel.options, **deepcopy(override.options)}
    return channel


def normalize_call_options(options, schema, *, data_dir: Path):
    """Check allowed fields before normalization; never reapply plugin defaults."""
    validate_workflow_options(options, schema)
    return normalize_options(options, schema, data_dir=data_dir, apply_defaults=False)
