# Lifecycle 任务

- 装配配置、凭据、插件注册视图、Collection、AI、Channel 和 Workflow。
- 启动时通过 `PluginRegistry` 发现 mock/logs 等插件，不初始化运行记录或正文存储。
- reload 只替换配置和插件注册视图；关闭时停止准入并释放当前调用资源。
- 使用标准 Python `logging` 记录生命周期和诊断事件，避免自建日志设施。
