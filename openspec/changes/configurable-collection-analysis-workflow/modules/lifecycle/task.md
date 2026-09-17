# Lifecycle任务

状态：已完成实现与专项验证，待主代理统一集成和全量验证。

依据：[Lifecycle设计](./design.md)、[总设计](../../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：配置、AI、Channel/Mock/Email、Workflow、Collection；API 通过工厂注入，最终 HTTP 生命周期由 Interaction 接线。

- [x] 装配 SystemConfig、CredentialManager、JSON ResourceStore、LangGraph SQLite checkpointer、SessionStore 和只读 SessionView；初始化失败保留明确错误并逆序清理，不开放运行准入。
- [x] 注册 history/logs/mock Collector 和 email/mock Channel，再扫描外部插件；只读注册视图及语义校验器按依赖注入，完成引用校验。插件缺失可降级；启动不访问实际来源/模型/通知平台。
- [x] 装配 Workflow 与 IntervalTrigger，定时/手动入口共用容量、enabled、快照和取消；资源更新后重建未来计划，不补跑错过触发。
- [x] resources reload 原子发布；plugins reload 原子关闭准入并暂停定时，活动冲突拒绝后恢复准入；无活动时关闭旧 owner 实例再重新注册、注入新视图，失败保留诊断。
- [x] 健康查询仅汇总本地状态、accepting_runs 与诊断，必要依赖不可用禁止运行，可选插件错误 degraded；后续成功检查可恢复状态。
- [x] 关闭先禁止新运行/定时，再有界收束所有session，释放客户端/渠道/插件，最后 SessionStore/checkpointer；日志采用标准 logging 的逐行 JSON、轮转和脱敏，供 logs Collector 读取。
- [x] 单测启动失败清理、定时重排/禁用/容量、reload 冲突/降级恢复、幂等关闭（60秒），lint、构建、临时配置完整装配烟测。

## 实现决策

- `start`、`reload`、`shutdown` 共用 `_lifecycle_lock`，并分别持有内部启动、reload、关闭 task；对外等待使用 `asyncio.shield`。调用方取消或超时不会取消正在收束的内部任务，下一次调用会继续等待同一任务。启动期间收到关闭请求时，启动阶段先清理已获取资源，再由关闭流程收束，避免并发泄漏。
- 清理任务按组件保存在 `_cleanup_tasks`，超时只返回 `cleanup_timeout`，不取消真实清理任务；后续调用复用该任务。清理顺序在 Workflow 未完成时不继续关闭其依赖的 AI、Channel、SessionStore 或 checkpointer，依据 [Lifecycle 设计](./design.md#关闭与清理) 的分层释放要求。
- 默认 `_SHUTDOWN_TIMEOUT=30.0` 秒用于 IntervalTrigger 和 Workflow；设计要求关闭时等待或取消活动 session 并完成状态写入，但未规定固定数值，因此采用有界窗口，超时明确失败并保留后续收束能力。默认 `_CLEANUP_TIMEOUT=10.0` 秒用于 AI、Channel、日志、SessionStore 和 checkpointer 等本地释放；AI 与 Channel 各自的本地关闭预算为 5 秒，10 秒为生命周期层留出包装调度和摘要汇总余量，依据 [AI task](../ai/task.md) 与 [Channel task](../channel/task.md) 的清理记录。
- 插件 reload 先暂停 Timing 并等待 `pause_admission()` 关闭准入，再检查活动运行；无活动时先 `unload_owner`，之后重新发现和发布注册视图。活动冲突恢复原准入/定时状态；半发布失败或调用方取消保持禁准入，后续只能通过显式成功 reload 恢复，不实现不存在的 `restore_registers` 伪回滚。单个插件失败写入 `DiscoveryReport`，其他有效插件继续发布并以 degraded 状态运行，依据 [Lifecycle 设计](./design.md#reload)。
- 健康检查只观察本地组件状态：ResourceStore、SessionStore、checkpointer、Workflow、IntervalTrigger、AI、ChannelManager 和 JSON log sink。检查失败立即禁止新运行，后续检查成功后同步恢复；不发起远程探测，避免伪健康时间和额外副作用。
- `log_file=None` 全程保留，不创建默认 `app.jsonl`；资源保存、删除和 resources reload 都在发布后重建未来 IntervalTrigger 计划，新运行从 ResourceStore 取得新快照，不补跑错过的触发。
- JSON 日志实现归独立日志代理；Lifecycle 只依赖 `JsonLogSink.error` 和本地 `check()`，不复制日志配置或探测远端。当前独立实现暂记录 `10 MiB * 5` 轮转默认，最终数值与日志专项测试以该代理结果协调。

## 专项验证

- `rtk proxy timeout 60s uv run pytest tests/test_lifecycle.py -q`：`15 passed, 1 warning`（LangGraph 既存弃用警告）。
- `rtk proxy uv run ruff check src/logagent/lifecycle/service.py src/logagent/lifecycle/__init__.py tests/test_lifecycle.py`：通过。
- `rtk proxy uv run ruff format --check src/logagent/lifecycle/service.py src/logagent/lifecycle/__init__.py tests/test_lifecycle.py`：通过。

未在此模块执行全量构建或全量测试；`logging.py`/独立日志测试和 Workflow 接口分别由对应代理负责，Lifecycle 专项测试中使用的接口已通过集成测试。
