# Workflow Agent Handoff

## ADDED Requirements

### Requirement: Handoff includes a declarative MCP invocation description

继续对话 SHALL 交接前一阶段采集来源名称、Cursor 配置中的原始 MCP 服务名称、工具名称和原始请求参数，并保留运行快照身份。该交接内容是给 Agent 的调用提示，不是已经选定或连接好的 MCP 对象，也不构成自动重放。

#### Scenario: Continue after MCP collection

- **WHEN** Workflow 使用 MCP 工具完成或失败后继续对话
- **THEN** Agent 获得来源名称、MCP 服务名称、工具名称和参数，可通过现有 `mcp` 代理自行查询 schema、修改参数并按当前对话需要调用

### Requirement: CLI remains CLI

CLI 来源 SHALL 交接来源名称以及 command/args 或 shell 描述，不自动进入 MCP 服务范围。

#### Scenario: Continue after CLI collection

- **WHEN** Workflow 只有 CLI 来源
- **THEN** Agent 获得来源名称和 CLI 指令，不获得全局 MCP 服务

### Requirement: Handoff is stable across recovery

恢复和分支 SHALL 使用已持久化的调用描述，不从当前全局资源重新推导名称或请求参数；Agent 是否调用由当前对话决定。

#### Scenario: Global configuration changes

- **WHEN** 交接后全局 MCP 配置发生变化
- **THEN** 原会话仍使用原服务 ID、工具和参数快照；可刷新目录但不得扩大交接范围
