# MCP Schema-First 重设计

## Why

`bf9fc1c` 已经引入官方 MCP SDK、MCP transport、工具目录和原始调用能力，但 Agent 入口仍是带 `action` 参数的总工具，Workflow 交接的也主要是服务范围。`f175e03` 中旧 Collector 的 `count`、Setter、Collector registry 和 `plugin` 路由不能作为新 MCP 的业务契约。

本变更重新定义 MCP 的边界：MCP 工具 schema 是目录、搜索、参数校验和调用的共同事实来源；Agent 只看到固定的 schema-first MCP 代理；Workflow 保存采集来源对应的 MCP 服务名、工具名和请求参数；旧 Collector 的错误策略迁移到 MCP 请求错误，不恢复整个采集器系统。

## Scope

- 使用官方 MCP SDK 作为 MCP 协议和 transport 实现。
- 复用 `bf9fc1c` 的 SDK connector、transport、目录缓存、schema 校验、原始结果和执行事实模型。
- 复用旧 Agent 的 `ToolDeclaration`、统一调度、事件记录和结果存档框架，但重写 MCP 路由和工具声明。
- 复用现有固定 `mcp` 代理的 `list`、`search`、`describe`、`call` 动作实现 schema-first Agent 交互，不新增平行顶层工具。
- MCP 目录探测优先使用 `server/discover`，不支持时兼容 `tools/list`。
- 通过 Cursor 风格 `mcpServers` JSON 导入 MCP；配置键名原样作为服务 ID。
- 从 MCP 返回的 `_meta.workflowweave_count` 读取业务计数；缺失时统一标记 `count_unavailable`。
- 将来源名称、MCP 服务名称、工具名称和请求参数作为调用描述交接给继续对话的 Agent，由 Agent 自己通过 `mcp` 代理发现和调用；CLI 来源交接来源名称和 CLI 指令。
- 将旧来源的 `stop`、`notice`、`skip` 错误策略应用到 MCP 请求错误。

## Out of scope

- 恢复 `CollectorManager`、Collector registry、Setter/template 或旧 `CollectorOutput`。
- 用旧 `count > 0` 判定 MCP 请求成功。
- 恢复旧采集器的格式化、字段选择和通知实现。
- 将 CLI 包装成 MCP。
- 将所有 MCP 工具 schema 注册为 Agent 原生工具。

## Capabilities

- `agent-interface`：固定 MCP schema 工具和原始调用结果。
- `mcp-runtime`：SDK transport、服务身份、目录、schema、探测、缓存和调用事实。
- `workflow-collection`：MCP 调用描述、计数状态和请求错误策略。
- `workflow-agent-handoff`：MCP/CLI 继续对话交接。

## Baseline evidence

- `f175e03`：旧 `ToolDeclaration`/Agent 调度框架和 Collector 时代的错误策略。
- `bf9fc1c`：MCP SDK runtime、stdio/SSE/Streamable HTTP、目录缓存、schema 校验和原始结果。
- 本轮用户决定：`_meta.workflowweave_count`、缺失为 `count_unavailable`、`server/discover` 优先、Cursor 键名作为服务 ID。
