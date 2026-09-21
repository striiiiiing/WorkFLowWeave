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


def resolve_source_call(
    source: SourceConfig, templates: Mapping[str, SetterTemplate],
    override: SourceOverride | None = None,
) -> SourceConfig:
    """Expand saved and call templates in order, preserving explicit empty values."""
    source = copy_model(source)
    layers = [(source.template, source.setters)]
    if override is not None:
        override = copy_model(override)
        layers.append((override.template, override.setters))
        source.options = {**source.options, **deepcopy(override.options)}
    setters = {}
    for template_id, explicit in layers:
        if template_id is not None:
            template = templates.get(template_id)
            if template is None:
                raise LogAgentError("invalid_reference", "来源引用的 Setter 模板不存在")
            if template.collector != source.collector:
                raise LogAgentError("invalid_reference", "Setter 模板与来源的 Collector 不同")
            setters.update(deepcopy(template.setters))
        setters.update(deepcopy(explicit))
    source.setters = setters
    source.template = None
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
