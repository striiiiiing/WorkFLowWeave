"""Pure source normalization, independent of resource persistence."""

from __future__ import annotations

import inspect
from copy import deepcopy

from pydantic import ValidationError

from logagent.errors import LogAgentError, validation_error
from logagent.models import JSONObject, SetterTemplate, SourceConfig, copy_model
from logagent.protocols import Collector
from logagent.schema import schema_defaults, validate_instance, validate_schema


def expand_source(
    source: SourceConfig,
    *,
    collector: Collector,
    template: SetterTemplate | None = None,
    options_defaults: JSONObject | None = None,
) -> SourceConfig:
    """Expand schema/plugin options and a referenced template without mutating inputs.

    Same-name values replace a whole value, including compound values and empty
    lists. The returned configuration no longer needs to look up its template.
    """
    try:
        source = copy_model(source)
        template = copy_model(template) if template is not None else None
    except ValidationError as exc:
        raise validation_error(exc) from None
    if source.collector != collector.name:
        raise LogAgentError("invalid_config", "来源与提供的 Collector 不匹配")
    if source.template is not None and template is None:
        raise LogAgentError("template_missing", "来源引用的 Setter 模板未提供")
    if template is not None and (
        source.template != template.id or source.collector != template.collector
    ):
        raise LogAgentError("invalid_config", "Setter 模板引用或 Collector 归属不匹配")

    options_schema = deepcopy(collector.options_schema)
    setters_schema = deepcopy(collector.setters_schema)
    validate_schema(options_schema)
    validate_schema(setters_schema)
    defaults = deepcopy(options_defaults) if options_defaults is not None else {}
    validate_instance(defaults, options_schema, path=["defaults"], partial=True)
    options = {**schema_defaults(options_schema), **defaults, **source.options}
    setters = deepcopy(template.setters) if template is not None else {}
    if template is not None:
        validate_instance(setters, setters_schema, path=["template", "setters"], partial=True)
    setters.update(source.setters)
    validate_instance(options, options_schema, path=["options"])
    validate_instance(setters, setters_schema, path=["setters"])
    semantic_validate = getattr(collector, "validate", None)
    if semantic_validate is not None:
        if not callable(semantic_validate) or inspect.iscoroutinefunction(semantic_validate):
            raise LogAgentError("invalid_config", "Collector.validate 必须为同步校验函数")
        try:
            result = semantic_validate(deepcopy(options), deepcopy(setters))
            if inspect.iscoroutine(result):
                result.close()
            if result is not None:
                raise TypeError("Semantic validation must return None")
        except Exception as exc:
            raise LogAgentError(
                "invalid_config",
                "来源选项或 Setter 未通过 Collector 语义校验",
                {"exception_type": type(exc).__name__},
            ) from None
    source.options = deepcopy(options)
    source.setters = deepcopy(setters)
    source.template = None
    return source
