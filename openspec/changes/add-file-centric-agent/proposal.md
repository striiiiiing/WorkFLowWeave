# 文件优先的 Agent 模块

## Why

系统已有采集、分析和通知 Workflow，但用户无法从某次 Workflow 的最终结果继续追问，也没有一个低 Token、可读文件优先的多轮 Agent 入口。把每个 Collector 注册成模型工具会让工具定义和提示词随插件数量增长；另建 Memory、History、搜索服务又会增加状态来源。

## What Changes

- 增加独立 Agent 会话服务，以 LangGraph 1.x `create_agent` 复用现有模型、Collector、Schema 和资源配置。
- 从 Workflow 历史结果创建 Agent 会话；结果对象作为 `{input}` 注入，来源 session 与 Agent 上下文保持绑定，但 Workflow 后续运行不自动切换既有会话。
- 默认只注册 `plugin`、`read`、`write`、`grep`、`shell` 五个工具。`plugin` 按需列出、读取 Schema 并单次调用 Collector；工具插件可独立关闭。Channel 继续作为会话绑定的双向通道，不暴露任意发送工具。
- 提供 `/new`、`/resume`、`/workflow`、`/compact`、`/append`、`/fork` 命令、优先级队列、树形分支和可编辑用户输入。
- 使用固定工作区、AGENTS.md、按日 Memory、历史笔记、原始 JSONL 和 Artifact；不增加记忆专用工具或向量数据库。
- 复用 LangChain 摘要中间件，以 200,000 tokens/90% 触发作为默认配置，原始历史与执行 checkpoint 分离；普通压缩和 fork 不删除链上中间 checkpoint，只在整条 thread 满足保留策略时清理。
- 提供可关闭的简单 bubblewrap Shell 沙箱、工作区级读并发/写独占，以及独立 Agent HTTP/SSE 和 Vue 页面。

## Capabilities

### New Capabilities

- `agent-runtime`：Workflow 结果续接、Collector 单次调用、工具插件、文件工作区、调度、沙箱、分支、压缩和执行状态。
- `agent-interface`：双向命令队列、会话/分支 API、事件流、文件 API 与前端交互。

## Impact

涉及 `src/logagent/agent/`、现有 AI/Schema/interaction/lifecycle/plugin registry，以及 `frontend/src/`。需要成组升级 LangChain/LangGraph 1.x，并在 Workflow 数据库副本上回归旧图。当前已有实现只是基线快照；本变更的设计和任务以新的 [design.md](design.md) 为准。

依据、默认值和实施验收见 [tasks.md](tasks.md)，前端分解见 [frontend.md](frontend.md)，外部证据见 [references.md](references.md)。
