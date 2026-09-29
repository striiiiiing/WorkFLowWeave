# Agent MCP Interface

## ADDED Requirements

### Requirement: Agent exposes a fixed schema-first MCP proxy

系统 SHALL 注册一个固定的 `mcp` 代理工具，其 `action` 至少支持 `list`、`search`、`describe` 和 `call`。固定 schema SHALL 不枚举服务或工具目录。

#### Scenario: List returns compact catalog

- **WHEN** Agent 调用 `mcp` 且 action 为 `list`
- **THEN** 返回服务身份、工具原名、截断描述、目录状态和分页信息，不返回完整参数 schema

#### Scenario: Describe returns complete schema

- **WHEN** Agent 调用 `mcp` 且 action 为 `describe`
- **THEN** 返回该工具的完整 `inputSchema`，schema 不以截断文本冒充完整定义

### Requirement: Calls use current schema and preserve raw results

`mcp` 的 `call` action SHALL 按服务身份和工具原名定位工具，按当前 schema 校验参数，并保留 MCP 原始结果及错误字段。

#### Scenario: Invalid arguments

- **WHEN** 调用参数不符合当前工具 schema
- **THEN** 调用在派发前失败并返回 schema 校验错误

#### Scenario: Mixed MCP result

- **WHEN** MCP 返回 content、structuredContent、`_meta` 和 `isError`
- **THEN** Agent 结果保留这些字段和原始顺序，不转成旧 Collector 输出

### Requirement: Agent calls are traceable

Agent MCP 调用 SHALL 记录实际服务、工具、调用上下文、阶段、结果状态和结果是否已知。

#### Scenario: Unknown result

- **WHEN** 请求已发出但连接在响应前断开
- **THEN** 标记结果未知，不自动重放该调用
