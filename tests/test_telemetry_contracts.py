"""AxonHub cache and paired JSON token measurement contracts."""

from __future__ import annotations

import pytest

from logagent.errors import LogAgentError
from logagent.telemetry import (
    TokenMeasurement,
    cache_ratio,
    compare_token_measurements,
)


def test_cache_ratio_uses_cached_input_as_the_numerator():
    assert cache_ratio(input_tokens=1000, cached_input_tokens=250) == pytest.approx(0.25)
    assert cache_ratio(input_tokens=None, cached_input_tokens=250) is None


def test_cache_ratio_rejects_impossible_counters():
    with pytest.raises(LogAgentError):
        cache_ratio(input_tokens=0, cached_input_tokens=0)
    with pytest.raises(LogAgentError):
        cache_ratio(input_tokens=100, cached_input_tokens=101)


def _measurement(input_tokens: int) -> TokenMeasurement:
    return TokenMeasurement(
        model="agentai",
        prompt_fingerprint="prompt-1",
        data_fingerprint="data-1",
        input_tokens=input_tokens,
        output_tokens=100,
    )


def test_compact_json_reports_signed_input_savings():
    comparison = compare_token_measurements(_measurement(1000), _measurement(640))

    assert comparison.direct_input_tokens == 1000
    assert comparison.compact_input_tokens == 640
    assert comparison.saved_input_tokens == 360
    assert comparison.savings_ratio == pytest.approx(0.36)


def test_token_pair_with_different_prompt_is_not_comparable():
    compact = TokenMeasurement(
        model="agentai",
        prompt_fingerprint="prompt-2",
        data_fingerprint="data-1",
        input_tokens=640,
        output_tokens=100,
    )

    with pytest.raises(LogAgentError, match="不可比"):
        compare_token_measurements(_measurement(1000), compact)
