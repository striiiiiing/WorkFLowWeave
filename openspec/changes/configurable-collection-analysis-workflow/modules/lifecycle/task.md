# Lifecycle 任务

- 装配配置、凭据、插件注册视图、Collection、AI、Channel 和 Workflow。
- 启动时通过 `PluginRegistry` 发现 mock/logs 等插件，并初始化（或复用）Workflow SQLite 运行存储。
- reload 只替换配置和插件注册视图；已运行 session 使用其冻结快照，关闭时停止准入、排空当前调用并保留可恢复记录。
- 使用标准 Python `logging` 记录生命周期和诊断事件，避免自建日志设施。
