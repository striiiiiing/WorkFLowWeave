# 契约任务

- 定义严格的 JSON-compatible 配置、快照、采集、分析和通知结果模型。
- 使用标准 `jsonschema` 完成插件 schema 声明与实例校验，不维护第二套 schema 图或类型推导系统。
- 定义插件注册、Collector、AI、Channel、凭据和当前调用上下文接口。
- Workflow 执行结果、阶段输入/输出/错误和投递回执由 SQLite 持久化；契约包含 session 查询、历史查询以及 `recover/resume` 恢复接口。凭据仍仅在运行时使用。
