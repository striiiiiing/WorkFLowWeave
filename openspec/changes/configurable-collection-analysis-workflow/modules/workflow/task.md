# Workflow 任务

1. 在每次运行开始时固定 `WorkflowSnapshot`，通过 LangGraph StateGraph 按顺序完成 collect、analyze、aggregate、notify、finish。
2. 维护并发限制、超时、取消和失败策略，并将状态与阶段结果写入 SQLite，支持取消后恢复。
3. 使用注入的 CollectorManager、AIService 和 ChannelManager；运行记录由 SQLiteRunStore 与 LangGraph `AsyncSqliteSaver` 管理，不序列化客户端或凭据。
4. 结果按统一模型返回；提供 `get_session`、`list_sessions`、`history`、`recover/resume` 查询和恢复接口。

## 执行记录（2026-09-15）

- 已完成：使用 LangGraph StateGraph 实现 collect → analyze → aggregate → notify → finish；阶段完成前后写入 SQLite 阶段日志和原生 checkpoint，支持来源/分析并发限制、全空与失败策略、fan-in、通知顺序、取消和容量准入。
- 已完成：注入 CollectorManager、AIService、ChannelManager 与冻结资源快照；SQLiteRunStore 保存 `run_sessions`、`run_stages`、`run_items`、`run_history` 和投递意图/回执，`recover/resume` 在重启后复用成功分支并重试失败分支。
- 已完成：通知发送前持久化 intent，已有回执在恢复时跳过；无回执的 intent 标记 `delivery_uncertain`，不自动补发。单个 SQLite 文件约束为一个执行器进程。
