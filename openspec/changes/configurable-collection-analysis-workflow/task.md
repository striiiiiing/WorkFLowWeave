# 实施计划

1. 完成严格数据模型、轻量 JSON Schema 校验和配置资源管理。
2. 完成 QwenPaw 风格的 manifest/backend/plugin.register 注册流程；mock 作为普通 Collector 插件加载。
3. 完成 Collection、AI、Channel 和基于 LangGraph 的可恢复 Workflow 调用链路。
4. 使用 Python 标准库 `logging` 负责诊断输出；logs Collector 只做有界读取。
5. API、CLI 和生命周期装配上述能力；Workflow 使用 SQLite 保存运行状态、阶段结果、投递回执和完整历史，支持重启后恢复。

## Workflow 持久化约定

- Workflow 使用同一个 SQLite 文件保存配置快照、运行状态、阶段结果、逐项结果、通知意图/回执和 `run_history`。默认复用注入资源仓库的 `location`；资源仓库使用 `:memory:` 时改用 `data/workflows.sqlite3`，也可通过 `database` 显式指定路径。
- 每次执行在开始时冻结 `WorkflowSnapshot` 和运行上下文。历史保存各阶段输入、输出、错误及事件正文，默认永久保留且不自动清理；凭据引用可进入配置快照，解析后的凭据不写入快照、历史或错误。
- `WorkflowService.recover(session_id)`（别名 `resume`）读取 LangGraph 原生 SQLite checkpoint 与阶段日志，复用已成功的采集/分析/聚合结果，只重试未完成项。已写入的投递回执不会重复发送；发送意图存在但没有回执时记录 `delivery_uncertain` 并停止补发，因此不承诺外部 exactly-once。
- 单个数据库文件只支持一个执行器进程；同一进程可创建多个服务实例，但同一 `session_id` 互斥。进程重启后可使用 `recover` 继续未完成运行。
