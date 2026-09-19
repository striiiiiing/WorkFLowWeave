# 装配与生命周期设计

[总设计](../../design.md) · [插件模型](../../contracts/data-models.md#6-能力描述和上下文) · [QwenPaw 依据](../../references/qwenpaw.md)

装配层是依赖组合入口，负责服务启停与依赖注入。插件读取、入口导入、注册和 owner 清理由配置模块承担；装配层只取得 `collectorRegister` 与 `channelRegister` 并分别注入数据采集模块和 Channel 网关。

Lifecycle 负责创建、连接和释放应用组件，并协调它们何时可以接收新任务。采集、分析、通知和 Workflow 执行由各业务模块承担。生命周期状态和准入决策集中在 `ApplicationLifecycle`，辅助模块提供校验、诊断和日志能力，避免各自维护一套启停状态。

## 模块分工与公共入口

| 文件 | 职责 |
| --- | --- |
| `service.py` | `ApplicationLifecycle`：依赖装配、启动、重载、健康检查后的准入调整和有序关闭。 |
| `services.py` | `ApplicationServices`：保存装配完成的服务引用，交给 Interaction 注入 API。容器字段冻结，其中的服务仍有运行状态。 |
| `resources.py` | 系统路径解析、资源语义校验接线、资源保存或删除后的定时计划刷新；跨线程通知回到所属事件循环。 |
| `health.py` | 本地组件探针、插件能力诊断和健康结果构造；准入变更由主类执行。 |
| `logging.py` | `JsonLogSink`：日志文件和轮转 handler 的安装、健康检查、释放及 logger 状态恢复。 |
| `formatting.py` | `RedactingJsonFormatter`：逐行 JSON 格式化、脱敏和 UTF-8 字节长度限制。 |

`ApplicationLifecycle` 提供 `start()`、`reload(scope)`、`health()` 和 `shutdown()` 四个入口。`from_file()` 通过配置模块读取 SystemConfig 后构造生命周期对象；`start()` 返回 `ApplicationServices`，启动完成前访问 `services` 返回 `not_ready`。Interaction 的 HTTP lifespan 调用启动和关闭入口，再将服务引用注入请求处理流程。

`ApplicationServices` 汇集 SystemConfig、凭据管理器、插件注册器、资源存储、SessionStore、只读 SessionView、checkpointer、CollectorManager、AIService、ChannelManager、WorkflowService、IntervalTrigger 和日志路径。业务模块通过构造参数取得所需依赖，Lifecycle 保留已取得资源的引用，以便在只完成部分装配时也能清理。

## 启动顺序

1. 取得并验证 SystemConfig、解析系统路径；启用日志时先建立 JsonLogSink，以记录后续启动诊断。
2. 打开 SessionStore，再进入 LangGraph SQLite checkpointer 上下文并完成 setup；存储不可用时不开放运行准入。
3. 创建配置模块的 PluginRegistry，发现并注册 history、logs、mock 等 Collector 插件及 Channel 插件，发布 `collectorRegister` 与 `channelRegister`；创建凭据管理器。
4. 将注册结果注入 CollectorManager 和 ChannelManager，向 AIService 注入渠道工厂及凭据解析器；创建资源存储，接入各模块校验器并解析五类资源及引用。已保存来源的插件缺失保留为诊断，执行时按 on_missing 处理。
5. 基于 SessionStore 建立只读 SessionView，将存储、查询接口和业务服务注入 WorkflowService；历史 Collector 通过执行上下文取得 SessionView。保持准入关闭，由 Workflow 对照运行任务与业务存档，经幂等运行时入口将遗留 created/running session 标记 interrupted，不自动恢复运行。
6. 创建 IntervalTrigger 并装载未来定时计划，发布 ApplicationServices，启动定时器并开放任务准入。Interaction 在启动完成后接入 HTTP 请求处理。

所有依赖由构造参数注入。健康检查汇总已知本地状态，不通过启动流程发送探测邮件、读取实际来源或调用付费模型。Channel 实例按快照配置首次使用时初始化并常驻，服务关闭时统一释放；服务启动不遍历所有目标建立远端连接。

## 插件注册协调

插件目录格式、`plugin.json`、`entry.backend`、`plugin.register(api)` 入口及 `collectorRegister`/`channelRegister` 发布规则由[配置模块](../config/design.md#插件发现与注册)定义。装配层不扫描插件目录，也不保留第二份 manifest、schema、owner 或能力注册表。

配置模块完成一次发现后输出两个只读注册结果：`collectorRegister` 注入 CollectorManager，`channelRegister` 注入 ChannelManager。类型、schema、实现/工厂在每一注册结果内保持同一条记录，业务模块的 `describe` 和 `validate` 直接从注入结果投影。加载时不调用 collect/send，不启动永久接收循环；单插件导入/注册异常由配置模块隔离并写入 DiscoveryReport。

## reload

`POST /api/reload?scope={scope}` 提供显式入口，scope 为 resources 或 plugins，默认 resources。没有后台文件 watcher。

resources：重新读取资源 JSON，完整验证后原子替换有效视图；失败保留上一版。当前调用已经取得的快照不变；成功后按新 Workflow 定义重建未来定时计划。系统路径、监听及全局上限仍通过重启生效。

plugins：仅在没有活动运行时允许，原子关闭准入并暂停定时触发后再检查活动数；存在活动运行返回冲突，不自动取消它们。调用配置模块按 owner 清理旧声明、读取 `plugin.json` 并重新导入入口，再把新发布的 `collectorRegister`/`channelRegister` 注入两个业务模块；装配层不复制或重建注册内容。失败插件保持不可用并报告诊断，其他有效插件可以使服务 degraded 后继续接收运行；不宣称任意 Python 导入副作用可回滚。

插件 reload 在没有活动运行的边界，先关闭受影响 owner 的渠道实例，再由配置模块清理旧注册并加载新代码。卸载是 reload 后 owner 不再存在的结果，移除其全部类型/schema/工厂；已保存资源由配置模块按引用规则处理。

活动冲突在没有关闭请求时恢复原有准入和定时暂停状态。单插件失败可作为诊断发布有效注册结果；注册视图发布中途失败或内部 reload 任务被取消时，则记录失败阶段并保持禁准入和定时暂停，直到显式 plugins reload 成功。普通健康检查或 resources reload 不清除这项恢复要求。

## 健康检查与运行准入

`health()` 汇总系统配置、凭据、ResourceStore、SessionStore、checkpointer、Workflow、IntervalTrigger、AI、Channel 和日志的本地状态，同时报告插件发现错误、已保存资源引用的缺失能力及重载诊断。启用日志时，日志 sink 是必需组件；`log_file=None` 时日志组件不阻止运行，也不创建默认日志文件。

本地检查可以查询数据库或调用 `JsonLogSink.check()` 写入本地探针记录，不进行远端模型、来源或通知平台探测。日志状态直接使用 sink 的检查结果；AI 的关闭状态取自其渠道管理器。组件探针异常转为包含组件名和异常类型的明确诊断。

| 状态 | 条件 | 新任务准入 |
| --- | --- | --- |
| `ready` | 必需组件正常，没有插件诊断，生命周期允许运行。 | 开放 |
| `degraded` | 必需组件正常且允许运行，可选插件存在诊断。 | 开放，具体运行仍按其引用的能力处理 |
| `unavailable` | 未完成启动、必需组件异常、正在关闭或插件重载，以及重载失败等待显式恢复。 | 关闭 |

健康查询会调整运行准入：必需组件异常时暂停新任务；后续检查恢复正常且没有关闭、插件重载或重载恢复要求时，重新开放准入。因此 `health()` 并非完全无副作用的查询。它不会取消已经运行的 session，也不会自动恢复失败的插件发布。

## 并发与取消

`start`、`reload`、`shutdown` 的内部流程共用 `_lifecycle_lock` 串行执行，避免装配、重载和释放同一组依赖时互相穿插。它们分别持有内部任务；并发启动、并发关闭和同一 scope 的并发重载复用尚未完成的任务。`health()` 不持有这把生命周期锁，其探针结果用于本次检查及准入判断。

对外使用 `asyncio.shield()` 等待内部任务。请求方取消或超时结束等待，不会取消已经启动的装配、重载或清理；再次调用时可以继续等待仍在执行的同一任务。这与内部任务本身被取消不同：内部启动取消进入清理流程，内部插件重载取消保留恢复诊断。

关闭请求先设置关闭意图并暂停定时触发，再等待生命周期锁；正在启动的流程在开放准入前检查关闭意图，并先清理已取得的资源。关闭准入通过 Workflow 的 `pause_admission()` 与任务触发共用的准入锁协调，保证已经通过检查、正在提交的任务先完成提交，再收束活动运行。

## 关闭与清理

关闭顺序为：禁止新准入 → 停止 IntervalTrigger → 由 Workflow/RunCoordinator 收束活动 session 并完成状态写入 → 关闭 AI 模型客户端 → 关闭 Channel 常驻实例及其插件资源 → 退出 SQLite checkpointer 上下文 → 关闭 SessionStore → 写入停止事件并关闭日志。ChannelManager 等待当前 send 的有界清理后统一 stop。

启动失败记录失败阶段、异常类型及清理诊断，并按相同依赖释放顺序清理已取得的资源；上层任务仍可能使用的依赖必须保留。每一步清理完成后才清空对应引用，某一步失败或超时则暂停后续释放，避免任务尚未收束就关闭数据库或渠道。

组件清理任务保存在 `_cleanup_tasks` 中。超时返回 `cleanup_timeout`，保留实际运行的任务；下次关闭复用并继续等待它。清理任务若已异常结束，本次记录错误，下次调用可以重新发起该步骤。全部资源释放完成后标记关闭完成，重复关闭直接返回；同一个生命周期对象关闭后不再启动。

当前默认准入暂停、定时器停止和 Workflow 收束各使用 30 秒等待预算，其余组件清理各使用 10 秒等待预算；这是每一步的等待窗口，不是整个 shutdown 的总超时。30 秒用于有界等待运行收束，10 秒为组件内部清理及调度汇总留出余量，数值沿用既有 [Lifecycle 实现决策](./task.md#实现决策)，本次说明不引入新的超时策略。

stop/shutdown 可重复调用，清理错误独立记录，不掩盖原始启动或业务失败。阻塞 SDK/线程必须有实际 I/O 时限；取消 async 包装并不强制终止线程。首版不运行无所属的后台任务。

## 验证要点

覆盖配置模块提供的目录插件注册结果注入、一个插件多能力、重复 ID/key、manifest 与 kind 不符、`entry.backend` 路径越界、入口导入失败、默认配置无效、注册原子性、插件 reload 活动冲突、卸载无残留和失败启动清理。验证 checkpointer 或 SessionStore 不可用时不开放准入、遗留 session 标记中断，以及渠道实例和数据库按序释放。

同时覆盖并发启动与关闭、调用方取消后内部流程继续完成、清理超时后复用任务且不提前释放依赖、插件发布失败后仅显式 plugins reload 恢复、健康检查故障与恢复、AI/日志关闭后的不可用状态，以及资源更新后未来定时计划的重建。
