# Workflow 任务

1. 在单次调用内固定 `WorkflowSnapshot`，按顺序完成 collect、analyze、aggregate、notify。
2. 维护内存中的阶段状态、并发限制、超时、取消和失败策略。
3. 使用注入的 CollectorManager、AIService 和 ChannelManager，不访问存储的运行状态。
4. 结果按统一模型返回；调用结束后不提供等待、历史查询或跨进程恢复。

## 执行记录（2026-09-15）

- 已完成：使用 LangGraph StateGraph 实现 collect → analyze → aggregate → notify → finish 单次调用图；阶段状态仅保存在调用内存中，支持来源/分析并发限制、全空与失败策略、fan-in、通知顺序、取消和容量准入。
- 已完成：注入 CollectorManager、AIService、ChannelManager 与资源快照，不读取运行历史或创建持久化 checkpoint。
