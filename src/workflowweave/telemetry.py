"""Comparable token and cache measurements with no invented defaults."""

from __future__ import annotations

from dataclasses import dataclass

from workflowweave.errors import WorkFLowWeaveError


def cache_ratio(*, input_tokens: int | None, cached_input_tokens: int | None) -> float | None:
    if input_tokens is None or cached_input_tokens is None:
        return None
    if type(input_tokens) is not int or type(cached_input_tokens) is not int:
        raise WorkFLowWeaveError("telemetry_invalid", "token 计数必须为整数")
    if input_tokens <= 0 or cached_input_tokens < 0 or cached_input_tokens > input_tokens:
        raise WorkFLowWeaveError("telemetry_invalid", "缓存 token 计数不可能")
    return cached_input_tokens / input_tokens


@dataclass(frozen=True, slots=True)
class TokenMeasurement:
    model: str
    prompt_fingerprint: str
    data_fingerprint: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int | None = None

    def __post_init__(self) -> None:
        if not all(type(value) is str and value for value in (self.model, self.prompt_fingerprint, self.data_fingerprint)):
            raise WorkFLowWeaveError("telemetry_invalid", "token 测量身份不完整")
        if type(self.input_tokens) is not int or self.input_tokens <= 0:
            raise WorkFLowWeaveError("telemetry_invalid", "输入 token 计数无效")
        if type(self.output_tokens) is not int or self.output_tokens < 0:
            raise WorkFLowWeaveError("telemetry_invalid", "输出 token 计数无效")
        if self.cached_input_tokens is not None and (
            type(self.cached_input_tokens) is not int
            or self.cached_input_tokens < 0
            or self.cached_input_tokens > self.input_tokens
        ):
            raise WorkFLowWeaveError("telemetry_invalid", "缓存 token 计数无效")


@dataclass(frozen=True, slots=True)
class TokenComparison:
    direct_input_tokens: int
    compact_input_tokens: int
    saved_input_tokens: int
    savings_ratio: float


def compare_token_measurements(direct: TokenMeasurement, compact: TokenMeasurement) -> TokenComparison:
    if (direct.model, direct.prompt_fingerprint, direct.data_fingerprint) != (
        compact.model,
        compact.prompt_fingerprint,
        compact.data_fingerprint,
    ):
        raise WorkFLowWeaveError("telemetry_incomparable", "两次 JSON token 测量不可比")
    if compact.input_tokens >= direct.input_tokens:
        raise WorkFLowWeaveError("telemetry_incomparable", "紧凑 JSON 未测得更少的输入 token")
    saved = direct.input_tokens - compact.input_tokens
    return TokenComparison(
        direct_input_tokens=direct.input_tokens,
        compact_input_tokens=compact.input_tokens,
        saved_input_tokens=saved,
        savings_ratio=saved / direct.input_tokens,
    )
