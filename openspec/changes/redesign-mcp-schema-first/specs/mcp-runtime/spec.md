# MCP Runtime

## ADDED Requirements

### Requirement: Runtime uses the MCP SDK

系统 SHALL 使用官方 MCP SDK 支持 stdio、SSE 和 Streamable HTTP，并复用配置版本隔离的工具元数据缓存。

#### Scenario: Same configuration uses same catalog

- **WHEN** 相同服务配置再次查询目录
- **THEN** 可读取匹配版本的元数据缓存，缓存不包含凭据和调用结果

### Requirement: Discover prefers server/discover

系统 SHALL 优先调用 `server/discover` 探测和刷新目录；服务不支持时 SHALL 回退到 `tools/list`。

#### Scenario: New server supports discover

- **WHEN** 服务支持 `server/discover`
- **THEN** 目录和健康状态优先由该接口获取

#### Scenario: Legacy server only lists tools

- **WHEN** 服务不支持 `server/discover` 但支持 `tools/list`
- **THEN** 使用 `tools/list` 完成兼容探测和目录刷新

### Requirement: Runtime separates request failure and count state

系统 SHALL 从 `_meta.logagent_count` 读取非负整数业务计数；字段缺失或非法时 SHALL 统一标记 `count_unavailable`，不得从正文推断。

#### Scenario: Zero count

- **WHEN** 请求正常返回且 `_meta.logagent_count` 为 0
- **THEN** 标记为空业务结果，不标记为请求失败

#### Scenario: Missing count

- **WHEN** 请求正常返回但缺少 `_meta.logagent_count`
- **THEN** 请求保持成功，计数状态为 `count_unavailable`

### Requirement: Runtime does not replay unknown calls

系统 SHALL 区分超时、传输错误、协议错误、工具错误和结果未知；结果未知的调用不得自动重放。

#### Scenario: Reconnect before dispatch

- **WHEN** 连接在工具请求派发前失效
- **THEN** 可单飞重连并重试一次原始请求

#### Scenario: Disconnect after dispatch

- **WHEN** 工具请求已发送后断线
- **THEN** 返回结果未知状态，不重放工具请求

### Requirement: Cursor configuration preserves service names

Cursor `mcpServers` 的键名 SHALL 原样作为服务 ID；导入 SHALL 显式处理凭据引用和无效配置。

#### Scenario: Flexible service name

- **WHEN** 配置键为 `Issue Tracker / Prod`
- **THEN** 服务 ID 保留该字符串，不因旧 ID 正则限制而改名
