# Workflow 任务

1. 在单次调用内固定 `WorkflowSnapshot`，按顺序完成 collect、analyze、aggregate、notify。
2. 维护内存中的阶段状态、并发限制、超时、取消和失败策略。
3. 使用注入的 CollectorManager、AIService 和 ChannelManager，不访问存储的运行状态。
4. 结果按统一模型返回；调用结束后不提供等待、历史查询或跨进程恢复。
