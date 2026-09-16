# Channel 网关任务

状态：本轮复核缺口已在工作树修复并通过验证，待提交。`1c97439` 是初版；下列任务现在由专项测试证明。

依据：[Channel 网关设计](./design.md)、[总设计](../../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：公共模型与协议、配置注册视图/凭据；Mock/Email 用测试替身替代后单独实施。

- [x] Manager 只消费注入注册表，校验 notification 能力及 schema；缺失类型、禁用目标、初始化失败具有准确回执。
- [x] 按 channel_id 和规范化有效配置版本持有常驻实例，首次 start 后复用，不能每次 send stop。并发首发只初始化一次；同一不支持并发的实例串行发送，旧快照不漂移到新目标。
- [x] 一次总 timeout 包含锁等待、凭据、创建、start、send；发送至多一次，不内部重试。区分未发送、明确失败、已接受和 delivery_uncertain；取消传播并保留已知投递事实。
- [x] 显式替换/owner 卸载在无活动引用时释放旧实例；关闭停止准入、等待有界清理、统一 stop，幂等且不吞清理错误。插件 reload 可注入新注册视图。
- [x] 测试实例复用、并发初始化、配置更新、禁用、总时限、取消、不确定投递和关闭（60 秒）；lint、构建、两个发送一次 start 的烟测。

## 初版实现与验证（2026-09-17，后续复核发现缺口）

- `ChannelManager` 已改为按 `(channel_id, 规范化有效配置)` 缓存常驻实例；首次使用在管理锁内创建并 start，后续发送复用；同一实例发送串行化，配置变化或旧快照产生不同缓存键，不会漂移到新目标。
- `stop` 进入幂等关闭状态，清空准入并对所有实例执行有界 stop；清理错误显式上抛。发送失败/超时保留是否已进入实例发送的 attempts 与 `delivery_uncertain` 信息。
- 验证：`tests/test_workflow_integration.py` 2 passed；相关 Ruff 与 diff 检查待本模块补充定向实例并发测试后再扩大。

### 决策依据与默认值

- 缓存键使用完整序列化 ChannelConfig 而非仅 channel_id，依据 Channel design 的“按 channel_id 与有效配置版本区分”，在当前模型没有显式 version 字段时用规范化配置快照表达版本。
- 缓存键排除 `enabled`/`timeout`：两者是调用策略而非目标身份；依据 design 回执表“enabled=False | skipped，attempts=0，不构造实例或解析凭据”，禁用配置不产生实例，预算差异也不应制造虚假配置版本、让并发首发重复建实例。
- 预算耗尽与插件超时分开：依据 design 回执表“到达发送总时限 | timeout，attempts 取决于是否已进入插件 send”，预算耗尽必须记 `timeout`；插件自己抛出的超时表示该次投递明确失败，记 `failed`/`delivery_failed`。
- stop 超时暂用 5 秒；该值只约束资源清理，不改变发送总 timeout，后续 Lifecycle 装配可注入统一关闭预算。

### 本轮复核缺口的修复（2026-09-17）

- 总预算：`send` 在准入前建立绝对 deadline，用一个 `asyncio.timeout` 覆盖准入等待、实例初始化锁、`create`/`start`、发送锁和插件 `send`；`entered` 只在调用插件前设置。阻塞事件循环的插件调用无法被 `asyncio.timeout` 取消，此时 deadline 检查抛内部 `_BudgetExhausted`，回执仍按 design“到达发送总时限”记 `timeout`；插件自身抛出的 `TimeoutError` 仍是 `failed`/`delivery_failed`。
- 活动引用与关闭：`_begin_send`/`_end_send` 维护每个缓存键的活动计数与 `_sends_idle`；`stop` 禁止准入后先等活动发送归零，再统一 `stop` 实例，`_stop_task` 让并发第二次 `stop` 等待同一次关闭，清理错误汇总为 `channel_stop_failed` 并把每条原因保留在 `details.errors`。
- 初始化失败清理：`create`/`start` 失败或被关闭打断时释放已创建实例；初始化错误与清理错误同时保留（`channel_initialization_cleanup_failed`），不再静默吞掉清理失败。
- 释放与 reload：新增 `release(config)`、`unload_owner(owner)`、`replace_register(view)`（`reload_register` 为别名）。释放前等待该键的活动发送归零，有在途发送时不中断；`replace_register` 只停止新视图中已移除类型的实例，仍存在的类型继续服务旧快照。
- 证据：新增 `tests/test_channel_manager.py` 18 项定向测试（并发首发只初始化一次、旧快照隔离、等待实例初始化与发送锁计入总时限、进入插件后超时的 delivery_uncertain、stop 等待在途发送且并发幂等、清理错误汇总、初始化失败清理、release/unload/reload）。全量 `468 passed`，Ruff 通过；Workflow 集成断言改为完整文本比较，能发现同一通知被重复写入。

### 未覆盖的边界

- `stop`/`release`/`unload_owner`/`replace_register` 的等待按缓存键独立计时，多实例时总时长上限为键数 × `stop_timeout`；当前靠装配层关闭预算约束，Manager 内未合并成单一预算。
- 等待在途发送超时后，`stop` 通过错误回执显式失败，不与在途发送并发停止实例；是否强制终止留给装配层决定。
- `_init_locks`/`_key_idle` 按曾创建过的缓存键保留，`release` 只移除实例条目；数量与历史配置版本同阶（每个键一个 Lock/Event）。不随实例回收是为了避免 `_wait_for_key` 等在已被移除的 Event 上而误报 `channel_release_timeout`。
