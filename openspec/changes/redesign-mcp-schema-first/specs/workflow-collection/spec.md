# Workflow MCP Collection

## ADDED Requirements

### Requirement: Collection stores an MCP invocation

MCP 来源 SHALL 保存服务 ID、工具名和原始请求参数，并调用共享 MCP runtime；不得依赖 Collector registry、Setter 或模板。

#### Scenario: Selected tool invocation

- **WHEN** Workflow 选择一个 MCP 工具
- **THEN** 运行记录保存服务、工具和请求参数，并按该 schema 调用

### Requirement: MCP request errors trigger workflow policy

`isError`、超时、传输/协议错误、服务越界、工具不存在和参数校验失败 SHALL 触发来源的 `stop`、`notice` 或 `skip` 策略。

来源的 `on_error` 是用户可配置选项；未配置时 SHALL 使用 `SourceConfig.on_error` 的默认值 `notice`，不得静默忽略 MCP 请求错误。Agent 直接调用固定 `mcp` 代理时不适用该 Workflow 策略，工具错误 SHALL 原样返回给 Agent。

#### Scenario: Stop on request error

- **WHEN** MCP 调用失败且策略为 `stop`
- **THEN** Workflow 停止后续阶段

#### Scenario: Skip on request error

- **WHEN** MCP 调用失败且策略为 `skip`
- **THEN** 当前来源被跳过，后续来源和允许的阶段继续执行

### Requirement: Empty count is not a request error

正常 MCP 响应的 `_meta.workflowweave_count = 0` SHALL 进入空业务结果处理，不触发请求错误策略。

#### Scenario: Empty but successful response

- **WHEN** MCP 正常返回且计数为 0
- **THEN** Workflow 获得空结果状态，不执行 `on_error`

### Requirement: Count absence is explicit

缺少或非法的 `_meta.workflowweave_count` SHALL 统一记录 `count_unavailable`，不得从正文或数组长度估算。

#### Scenario: Count unavailable

- **WHEN** MCP 正常返回但没有合法计数字段
- **THEN** Workflow 保留原始结果并记录 `count_unavailable`
