"""Invocation overlays shared by workflows and interactive agents."""

from copy import deepcopy
from pathlib import Path

from workflowweave.config.normalize import normalize_options
from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import (
    ChannelConfig,
    ChannelOverride,
    SourceConfig,
    SourceOverride,
    copy_model,
)
from workflowweave.schema import validate_workflow_options


def select_source_call(
    source: SourceConfig | None, override: SourceOverride | None = None,
) -> SourceConfig:
    """Select a workflow's detached source or its shared source."""
    if override is None or override.source is None:
        if source is None:
            raise WorkFLowWeaveError("invalid_reference", "Workflow 引用的数据源不存在")
        return source
    if source is not None and override.source.id != source.id:
        raise WorkFLowWeaveError("invalid_reference", "脱离的数据源快照与工作流绑定不匹配")
    return override.source


def resolve_source_call(
    source: SourceConfig | None,
    override: SourceOverride | None = None,
) -> SourceConfig:
    """Apply MCP arguments and input limits to an independent source copy."""
    selected = copy_model(select_source_call(source, override))
    if override is None:
        return selected
    if override.arguments is not None:
        if selected.call.kind != "mcp":
            raise WorkFLowWeaveError("invalid_config", "arguments 覆盖只适用于 MCP 来源")
        selected.call.arguments = {**selected.call.arguments, **deepcopy(override.arguments)}
    selected.limits = selected.limits.model_copy(update={
        key: value for key, value in override.limits.model_dump().items() if value is not None
    })
    return selected


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
