"""Pure schema-annotated option normalization."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from workflowweave.errors import WorkFLowWeaveError, validation_error
from workflowweave.models import Credential
from workflowweave.schema import (
    schema_defaults,
    transform_annotations,
)

_CREDENTIAL = TypeAdapter(Credential)


def normalize_options(options, schema, *, data_dir: Path, apply_defaults: bool):
    """Only explicit schema annotations identify paths and credential fields."""
    if apply_defaults:
        options = {**schema_defaults(schema), **options}

    def normalize(value, rule):
        if not isinstance(rule, dict):
            return deepcopy(value)
        if rule.get("x-workflowweave-credential") is True and value is not None:
            try:
                return _CREDENTIAL.validate_python(value).model_dump(mode="json")
            except ValidationError as exc:
                raise validation_error(exc) from None
        if rule.get("x-workflowweave-path") is True:
            if not isinstance(value, str) or not value or "\x00" in value:
                raise WorkFLowWeaveError("invalid_config", "声明的路径必须为非空有效字符串")
            try:
                path = Path(value)
                return str((path if path.is_absolute() else data_dir / path).resolve())
            except (OSError, ValueError, RuntimeError):
                raise WorkFLowWeaveError("invalid_config", "声明的路径无法解析") from None
        return deepcopy(value)

    return transform_annotations(options, schema, normalize)
