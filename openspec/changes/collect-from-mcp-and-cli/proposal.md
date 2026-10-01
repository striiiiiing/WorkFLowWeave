# 通过 MCP 或 CLI 采集 Workflow 输入

## Why

现有来源依赖项目内的 Collector 实现，且把来源调用、数据处理和业务计数放在同一采集契约中。用户希望保留按来源配置参数的使用方式，改由 MCP 工具或 CLI 命令取得内容，再由 Workflow 对 JSON 内容统一处理和选择传给 AI 的格式。

## What Changes

- 采集来源可选择 MCP 工具及调用参数，或 CLI 命令及参数；用户可为 CLI 配置实际执行的指令。
- 获取原始内容与 Workflow 转换分开。JSON 内容可应用字段 token 限额及 Workflow 级格式转换；非 JSON 内容保留原有文本表示，仅应用适用的 token 限额。
- Workflow 可选择不转换、ISON、TOON、ZON、Markdown 或 CSV，并配置总输入、单项及字段 token 限额。单项和字段限额允许来源覆盖，格式和总输入限额不允许来源覆盖。
- 不再生成或向 AI 输入自动附加采集业务计数；有计数分析需求时交给 Workflow AI。
- 增加 Workflow、采集配置视图和 Agent 共用的 MCP 基础能力，统一服务配置、工具目录、schema、按需连接与原始调用。
- 继续对话时向 Agent 运行时交接本次 Workflow 的 MCP 服务绑定；Agent 采用 pi-mcp-adapter 的单代理模式按需发现、查看 schema 和调用原始 MCP，避免全量工具 schema 常驻模型上下文。CLI 来源不因此成为 MCP。

## Capabilities

- `collection`：MCP/CLI 来源、原始结果和失败状态。
- `mcp-runtime`：共享 MCP 服务身份、目录缓存、连接生命周期和原始调用边界。
- `workflow`：JSON 转换、格式选择、token 限额与 AI 输入。
- `agent-interface`：MCP 会话交接、工具发现、schema 按需暴露及 Agent 原始调用。

本变更的行为契约见 `specs/`；格式选择说明见 [formats.md](formats.md)。既有设计文档及实现不在本次文档编写范围内。
