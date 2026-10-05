# 将 Workflow Agent Task 移植到当前运行时

## Why

`77a3253` 所在代码树已经完成 Workflow Agent Task 的实现和测试，但当前主线已切换到 LangGraph Workflow v4、原生 FastAPI SSE 和 MCP schema-first。直接合并旧分支会恢复已淘汰的 Workflow 图、PluginGateway 和第二套会话来源。

## What Changes

- 保留 `workflow-agent-task-execution` 与 `align-workflow-prompt-contract` 的产品契约和 OpenSpec 记录。
- 将 Agent Task 适配到当前 `WorkflowRunner`、`WorkflowContext`、`AgentService` 和 MCP binding。
- 保留 Task/FanIn 级 Agent 配置、会话元数据、工具白名单、冻结模型配置、取消和幂等首轮执行。
- 新增当前架构的实施记录和验证边界。

## Scope Boundary

- 不 cherry-pick 旧 Workflow graph、PluginGateway、CollectorGateway 或旧前端目录。
- 不修改已有 proposal/design；当前架构差异由本 change 的 task 记录。
- 普通 LLM Task、现有 Agent 继续会话和父 Workflow 结果持久化语义保持兼容。
