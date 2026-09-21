# 文件优先的 Agent 模块

## Why

现有系统能配置采集、模型分析和通知工作流，但缺少可以按用户问题选择采集器、读取历史、继续调查并回答的会话入口。把每个插件都绑定成模型工具会不断增加提示词，把记忆、历史、搜索分别实现为专用服务又会增加代码和状态来源。

2026-09-21 用户要求设计基于 LangGraph 的 Agent：复用插件 Schema 和单次调用，少量可关闭的工具，读并发、写串行，可关闭的简单沙箱，自动压缩，常驻 AGENTS.md，以及由 Agent 自己维护的按日 Memory 和历史文件，并包含前端设计。本变更交付设计与实施任务；不表示功能已经实现或验收。

## What Changes

- 增加独立 Agent 会话服务，复用现有 AI Provider、CollectorManager、ChannelManager、插件发现和 Schema 校验；Collector/Channel 每次执行都是一次请求。
- 默认工具面为 `plugin`、`read`、`write`、`grep`、`shell`；`plugin` 按需发现和调用既有能力，其余能力通过工具插件注册并可关闭。
- 复用 LangGraph 执行/持久化和 LangChain 自动摘要中间件，工具正文文件化，压缩阈值按实际上下文预算配置。
- 使用普通文件承载常驻说明、按日记忆、可编辑历史笔记及可读运行记录；不增加记忆工具或向量数据库。
- 提供会话、工具结果、文件查看/编辑、上下文用量与简单配置的前端入口。

## Capabilities

### New Capabilities

- `agent-runtime`：插件调用、工具注册与调度、文件上下文、沙箱、压缩和执行状态。
- `agent-interface`：会话 API、事件流、文件 API 和前端交互。

## Impact

设计涉及 `src/logagent/agent/` 新模块，以及现有 config/schema/AI/lifecycle/interaction 的集成点和 `frontend/src/` 新会话入口。实现时需要协调 LangGraph/LangChain 依赖版本，扩展插件种类；现有 Workflow 的业务语义与既有设计文件保持独立。

技术决策见 [design.md](design.md)，前端见 [frontend.md](frontend.md)，证据见 [references.md](references.md)，依据、默认值和实施验收见 [tasks.md](tasks.md)。
