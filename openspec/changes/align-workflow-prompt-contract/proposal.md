# 对齐 Workflow 与 Agent 的 Prompt 契约

## Why

源端分层提示词允许差异指令为空，缺少单任务优化配置；本地 Agent 适配仍把旧 prompt 当输入模板，不能遵循用户明确的三层消息及继承规则。用户于 2026-10-04 授权按最新契约修改不符的 Change 与实现。

## What Changes

- 统一普通和 Agent 分析的三层消息与 Task → Workflow 覆盖优先级，Human 输入模板和差异指令必填。
- 常规汇总的输入默认仅来自上一阶段结果；普通汇总在单任务同模型时可复用完整原分析上下文。
- “采用单任务优化”默认开启，只在普通汇总高级模式显示；Agent 汇总永远使用常规方案。
- 显式迁移旧资源与历史快照，保留历史恢复；缺少可迁移差异指令的资源明确报错并保留原文件。

## Capabilities

- `workflow-prompts`：修订活动变更 layer-workflow-prompts 的 Prompt 必填、汇总输入和优化规则。
- `workflow-agent-tasks`：修订 workflow-agent-task-execution 的共享继承和 Agent 汇总例外。

## Impact

影响模型、资源持久化、AI 消息组装、Workflow/Agent 执行与前端编辑器。plugins、Collector 接口、私有 MCP/CLI 兼容不在范围内。
