# Workflow Task Agent 执行

## Why

Workflow 当前的分析和汇总节点都通过单次 `AIService.execute()` 调用模型。已有 Agent 模块具备会话、工具、事件流和结果展示能力，但 Workflow 还不能在单个任务上选择 Agent 执行，也不能把 Agent 的过程暴露给用户。

本次变更将 Agent 作为 Task 的一种执行方式接入。模型、系统提示词、输入提示词和用户提示词继续复用 Workflow 现有字段；工具选择也归属于单个 Task。Analyze 子图不增加统一的工具或提示词配置。

## What Changes

- `AnalysisTask` 和可选的 `FanInConfig` 增加 Task 级 `agent_mode` 与 `agent_tools`。
- `agent_mode=false` 保持现有单次 LLM 执行；`agent_mode=true` 创建 Agent 会话、提交一次任务并等待结果，再转换回原有 `AnalysisResult`。
- 抽取并复用现有“从 Workflow Session 创建 Agent 会话”的接口：只有 Workflow Session ID 时创建继续会话，同时带 `task_id` 时创建 Workflow 子任务会话。
- Agent Session 明确记录 `standalone`、`workflow_continue` 或 `workflow_subtask` 三种来源类型，并记录 Workflow Session ID 与可选 Task ID。
- Workflow 子任务继续使用现有 Agent 事件、SSE 和 `AgentTranscript` 展示；用户后续可以继续发送消息，但不会回写父 Workflow 结果。

## Capabilities

- `workflow-agent-tasks`：Workflow 分析任务和汇总任务可独立选择单次 LLM 或 Agent 执行，并保留原有模型和提示词语义。
- `agent-workflow-sessions`：Agent 会话可以由 Workflow 结果或指定 Task 结果创建，并保留可追溯的来源标签。

## Scope Boundary

- 不把 Agent 图嵌入 Workflow 父图；Workflow 子任务使用现有 Agent Session 的检查点和事件日志。
- 不增加 Analyze 子图级工具、提示词或模型配置。
- 不改变普通 Agent 会话和现有 Workflow 继续会话的交互语义。
