## Purpose

建立可复现的 AxonHub 缓存率与 JSON token 对比口径，让部署报告能区分输入、输出、缓存命中和真实节省，避免用不同请求或估算值作性能结论。

## ADDED Requirements

### Requirement: AxonHub cache metrics are read with an explicit denominator

The system SHALL record the measurement window, model/request identity, input tokens, cached input tokens, output tokens, cache misses when available, and the formula used for cache ratio. A missing metric SHALL be reported as unavailable rather than treated as zero.

#### Scenario: Cache ratio is available

- **WHEN** an AxonHub observation contains input and cached-input token counters for the measured Workflow requests
- **THEN** the report calculates `cached_input_tokens / input_tokens`, includes the raw counters and window, and does not combine unrelated requests

#### Scenario: Cache counter is unavailable

- **WHEN** AxonHub does not expose a required counter for the selected window
- **THEN** the report marks cache ratio unavailable and identifies the missing counter without inventing a low or high rate

### Requirement: Compact JSON is compared with the direct JSON baseline

The system SHALL compare direct JSON and compact JSON using the same source data, model, prompt, request options, and measurement method. It SHALL report both token counts and the signed savings percentage, and SHALL not claim savings when the compact request is not the smaller measured input.

#### Scenario: Compact JSON reduces input tokens

- **WHEN** paired measurements use identical data and the compact request has fewer input tokens
- **THEN** the report shows both counts and `(direct - compact) / direct` as the savings percentage

#### Scenario: Pairing is invalid

- **WHEN** the two requests differ in data, model, prompt, or token accounting method
- **THEN** the comparison is rejected as incomparable instead of being reported as a saving
