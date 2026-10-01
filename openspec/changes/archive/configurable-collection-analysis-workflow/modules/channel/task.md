# Channel 网关任务

状态：本轮复核缺口已修复、验证并提交（`d273cfb`、`ad75c7b`、`ebebb13`、`340aae9`，发送预算共享见下）。`1c97439` 是初版；下列任务现在由专项测试证明。

依据：[Channel 网关设计](./design.md)、[总设计](../../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：公共模型与协议、配置注册视图/凭据；Mock/Email 用测试替身替代后单独实施。

- [x] Manager 只消费注入注册表，校验 notification 能力及 schema；缺失类型、禁用目标、初始化失败具有准确回执。
- [x] 按 channel_id 和规范化有效配置版本持有常驻实例，首次 start 后复用，不能每次 send stop。并发首发只初始化一次；同一不支持并发的实例串行发送，旧快照不漂移到新目标。
- [x] 一次总 timeout 包含锁等待、凭据、创建、start、send；发送至多一次，不内部重试。区分未发送、明确失败、已接受和 delivery_uncertain；取消传播并保留已知投递事实。
- [x] 显式替换/owner 卸载在无活动引用时释放旧实例；关闭停止准入、等待有界清理、统一 stop，幂等且不吞清理错误。插件 reload 可注入新注册视图。
- [x] 测试实例复用、并发初始化、配置更新、禁用、总时限、取消、不确定投递和关闭（60 秒）；lint、构建、两个发送一次 start 的烟测。

## 本次修正与主代理审查（2026-09-17）

- 对照总 design 的固定快照、无重复投递、有界生命周期，以及 Channel design 的实例复用规则，主代理审查了 `1c97439` 后全部新增网关代码和测试。本轮未改 proposal/design。
- 缓存键由 channel_id 和有效配置序列化生成，排除 enabled/timeout：两者是调用策略，不改变目标身份；有效 options 固定后独立复制，旧快照与新目标各自持有实例。每键初始化锁隔离，慢目标不占用其他目标的初始化锁。
- 一次发送预算覆盖准入、初始化锁、create/start、发送锁和 send。进入插件 send 前才计 attempts=1；无内部重试。绝对 deadline 补充事件循环被阻塞时的预算检查；插件自身 TimeoutError 与总预算超时分开。取消后即使插件 start 吞掉取消，也不继续发送。
- 主代理发现并修复：原始清理异常文本泄露、同名插件替换沿用旧实例、卸载排空期间仍接收新发送、停止超时后丢失实例引用、初始化失败后清理任务失去归属。
- owner 卸载先关闭准入，再等待活动引用；替换比较实际注册实现，同名替换也释放旧实例。失败保留旧注册及被阻止的准入，不能继续向正在关闭的实例发送。
- stop 先关闭准入并等待活动调用；等待超时则取消活动调用，再有界等待释放引用。所有实例并行清理；每个实例持有唯一 stop task，超时不丢失所有权，后续 stop 可继续等待。初始化失败的实例同样保留到清理完成；异常仅保存安全类型与固定说明。
- 默认 stop_timeout=5 秒，定位为本地资源释放预算，允许 Lifecycle 注入正有限值。stop 的活动排空、取消收束和实例清理各有独立预算；release/unload 对各配置键逐个有界等待，不承诺一次操作只有一个 5 秒总预算。此处依据设计“每个清理步骤有界且可重复”，不影响发送总预算。

## 验证

- Channel/Mock/Workflow 集成定向 49 passed，3.38 秒，exit 0（其中 Channel 32 项、Mock 15 项、集成 2 项）。
- 相关 Ruff 通过；构建与真实文件两次发送仅一次创建 smoke、全套结果在收取退出码后补录。

提交前验证：全套 490 passed，34.13 秒，exit 0；uv build 成功；真实文件两次发送仅一次创建、完整文本相等及重复 stop smoke 成功。所有审查由主代理完成。

后续装配审查发现只读注册表每次 get 都返回新包装对象，不能用包装对象身份判断插件变化。改为比较 create 实现、schema、能力与 owner；新增真实 PluginRegistry 回归证明未变更实例不会被重建。Channel 定向 33 passed（exit 0），Ruff 通过。

对照 Channel design 的失败诊断要求补充复核：失败回执统一写入标准 logging，仅包含 event、session/channel/output ID、错误码、状态和不确定性，不包含通知正文、凭据或原始异常。新增日志脱敏回归 1 passed（exit 0），Ruff 通过。

Email 实施中复核到一处预算缺陷：常驻实例按 channel_id 与有效配置复用，timeout 被排除在缓存键之外，因此适配器若沿用创建时的 timeout，后续发送会继续使用旧快照的时限。设计第 32 行要求“每次发送的 timeout 覆盖等待实例可用、必要准备和发送”，故由 Manager 在调用 send 前把本次绝对 deadline 放入 `logagent.channel.context` 的 ContextVar，内置适配器据此读取剩余预算；插件 send(notification) 签名与语义不变，不读取该上下文也不会改变行为。Email 新增常驻连接复用下的当前快照时限回归（`tests/test_email_channel.py::test_reused_connection_obeys_current_snapshot_timeout`）。

主代理验证：全套 520 passed，35.07 秒，exit 0；本地 SMTP 端到端烟测一次 DATA 受理、正常收尾，exit 0。

## Manager 精简与设计对齐（2026-09-19）

依据：本模块 [design.md](./design.md) 的“实例绑定与发送”“验证要点”，以及 [Manager 四层设计](../manager%20design.md) 的“调用与实例身份”。本次设计不变，实施记录追加在当前任务内。

- [x] 合并初始化与入表失败的清理路径、重复实例查询和发送失败回执；配置校验只在本次发送总预算内执行一次。保留插件自身 TimeoutError 与总预算耗尽的区别，以及取消传播、失败日志和投递不确定性。
- [x] 活动发送统一存入一份任务映射，删除并行维护的按键计数、渠道信息及空闲事件。每次发送有独立完成信号，release/unload/stop 等待发送结束，不等待外层 Workflow task 结束；初始化中的发送同样计入活动引用。
- [x] 释放状态直接使用唯一 release task，删除重复释放事件。新发送只等待该任务结束再重新准入，释放异常仍由 release 调用方接收；释放排空超时不连带失败仍可用实例上的发送，已进入关闭的实例仍拒绝发送。等待者超时或取消不会取消清理任务。
- [x] 保留快照身份、实例/调用 options 分离、并发单次初始化、串行发送、旧实例复用和一次投递语义。删除入表前的重复注册查询，依据为 replace_register 先阻止准入、排空活动引用，再切换只读注册视图。
- [x] 新增 options/timeout 复用隔离、释放等待者超时/取消、释放排空失败隔离，以及真实 mock 追加文件与调用方生命周期隔离的回归测试。
- 默认值沿用已有实现：stop_timeout=5 秒仍是每个清理步骤的预算，依据本任务 2026-09-17 的清理预算说明；发送预算使用本次 ChannelConfig.timeout，不引入新默认值。
- 验证：`timeout 60s uv run pytest -q tests/test_channel_manager.py tests/test_channel_mock.py tests/test_email_channel.py tests/test_workflow_integration.py tests/test_workflow_overrides.py`：99 passed，15.48 秒，exit 0；有一条第三方 LangGraph 反序列化默认值将变更的预告警告。相关 Ruff、`git diff --check` 及 `uv build` 均通过。
- 独立验收：真实 PluginRegistry → ChannelManager → MockFileChannel，单次发送回执为 `status=success, attempts=1, error=null`；逐字验证保留已有内容、UTF-8 标题和多行正文追加，metadata 不改变路径，重复 stop 成功。输出保留在 `/tmp/logagent-channel-acceptance-mzzzapzs/notification.txt`。
