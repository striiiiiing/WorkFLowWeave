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

## 2026-09-19 可读性重构

依据：用户要求拆分并精简 lifecycle；[Lifecycle 设计](./design.md) 的依赖装配、本地健康检查、reload 与有序清理职责保持一致。本次为实现层结构性重构，设计不变，更新当前 task。

- [x] `services.py` 集中定义装配结果；`resources.py` 承担路径解析、资源校验适配和发布后调度通知。公共导出和构造注入参数沿用当前实现。
- [x] `health.py` 集中本地探针、组件结果构造和插件诊断。`service.py` 继续唯一负责准入变更及重载恢复状态，避免辅助模块持有第二份生命周期状态。
- [x] 删除可由 `_services` 推导的 `_started`、与关闭完成同步的 `_shutdown`、仅赋值和清空的 `_checkpointer`；合并插件重载的重复错误处理。保留明确的清理依赖顺序及超时任务复用。
- [x] 日志健康状态直接取 `JsonLogSink.check()`，移除生命周期层对其 handler/stream/error 的重复判定，依据本任务既有日志接口约定。AI 关闭状态从当前 `AIService.channels` 管理器取得，适配工作区已完成的 [AI Channel 拆分](../ai/task.md)，移除旧字段缺失时误报可用的路径。
- [x] 日志脱敏/格式化拆入 `formatting.py`，sink 留在 `logging.py`，保留原公共导入路径；重复序列化分支按原字段裁剪顺序合并。
- [x] 完成生命周期、日志、Workflow 及 Interaction 回归、lint/format、包构建和临时目录完整装配烟测。

默认值依据：沿用本 task 原有 30 秒关闭预算、10 秒组件清理预算和日志 10 MiB / 5 份轮转配置；本次不增加超时、后台任务或新的恢复策略。重构前专项基线：23 passed（60 秒硬超时）。

验证结果：

- `timeout 60s uv run pytest tests/test_lifecycle.py tests/test_lifecycle_logging.py tests/test_workflow_lifecycle.py -q`：26 passed，包含新增 AI/日志关闭健康状态及日志探针异常恢复验证。
- `timeout 60s uv run pytest tests/test_interaction.py tests/test_workflow_lifecycle.py tests/test_workflow_interval.py tests/test_workflow_integration.py tests/test_workflow_overrides.py tests/test_workflow_recovery.py tests/test_resource_store.py -q`：98 passed。
- `uv run ruff check src/logagent/lifecycle tests/test_lifecycle.py` 和对应 `ruff format --check`：通过。
- `uv build --out-dir /tmp/logagent-lifecycle-build`：sdist/wheel 构建成功，wheel 包含所有新拆分模块。
- 临时目录下真实 Lifecycle + FastAPI TestClient：健康检查 ready、resources/plugins 两种重载、恢复准入、幂等关闭及 JSON 启停日志均通过；未访问远端服务。
- 测试仅出现 LangGraph/Starlette 已有弃用警告；本次变更范围内 `git diff --check` 通过。主文件由 1044 行缩减至 621 行，模块总行数由 1475 行缩减至 1381 行（含新增模块和导入）。

### 2026-09-20 默认资源与前端联调
- 依据 lifecycle/design.md 的启动步骤 3–4，能力注册继续由 PluginRegistry 承担；本次补齐的是供 workflow 引用的资源实例。
- ResourceStore 接受装配层提供的 initial_resources，仅新文件创建时统一校验并原子写入，已有文件及用户删除保持不变。
- 默认 mock/history/logs 来源沿用各自 schema 默认参数；文件通知使用 mock 类型和 data_dir 下 notifications.txt，避免虚构邮件账号或 AI 凭据。logs 使用既有 CollectionContext.log_path，需配置 log_file。
- 当前空资源目录通过已有 save(create) 接口补齐；未修改 proposal/design。
- 验证新增 API 启动/默认资源/删除后重启测试；浏览器 workflow 测试补充删除与列表复核。

### 2026-09-30 启动耗时剖析与终端提示决策
依据：用户要求先找出启动中最耗时的部分，再决定是否增加终端提示；本次只更新实现任务记录，不修改 proposal/design。

- 实测临时空数据、复制当前 `data/` 的 Lifecycle 装配均约 `0.30–0.44s`；Lifecycle 内最慢阶段是插件发现，约 `0.18–0.19s`，其余阶段更短，不足以证明逐阶段终端提示有价值。
- CLI 冷启动的主要等待发生在 `import logagent.lifecycle.service`，约 `13.2s`；其中 `logagent.mcp` 约 `4.2s`、Workflow runner 约 `5.9s`。这段等待发生在进入 `ApplicationLifecycle.start()` 之前，因此在 lifecycle 阶段内打印不能覆盖用户感知的卡顿。
- [x] 将运行时导入移至 `start` 命令执行点，并在导入前通过 stderr flush 输出“正在加载运行时模块”；导入完成后提示即将读取配置并装配后端。
- [x] 不在 Lifecycle 的亚秒阶段逐个输出终端消息；服务就绪继续由 Uvicorn 的 `Application startup complete` 报告，避免重复输出。
- [x] CLI 导入回归测试确认导入命令模块不会提前加载生命周期运行时，保持非 `start` 命令的轻量路径。
