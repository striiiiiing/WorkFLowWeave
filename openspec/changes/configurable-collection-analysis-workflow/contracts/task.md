# 契约任务

- 定义严格的 JSON-compatible 配置、快照、采集、分析和通知结果模型。
- 使用标准 `jsonschema` 完成插件 schema 声明与实例校验，不维护第二套 schema 图或类型推导系统。
- 定义插件注册、Collector、AI、Channel、凭据和当前调用上下文接口。
- 明确所有执行结果只在当前调用内存在，不设计运行状态、历史或恢复接口。
