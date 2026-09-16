# Channel 网关任务

状态：待执行，完成后在本文件记录提交前验证结果。

依据：[Channel 网关设计](./design.md)、[总设计](../../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：公共模型与协议、配置注册视图/凭据；Mock/Email 用测试替身替代后单独实施。

- [ ] Manager 只消费注入注册表，校验 notification 能力及 schema；缺失类型、禁用目标、初始化失败具有准确回执。
- [ ] 按 channel_id 和规范化有效配置版本持有常驻实例，首次 start 后复用，不能每次 send stop。并发首发只初始化一次；同一不支持并发的实例串行发送，旧快照不漂移到新目标。
- [ ] 一次总 timeout 包含锁等待、凭据、创建、start、send；发送至多一次，不内部重试。区分未发送、明确失败、已接受和 delivery_uncertain；取消传播并保留已知投递事实。
- [ ] 显式替换/owner 卸载在无活动引用时释放旧实例；关闭停止准入、等待有界清理、统一 stop，幂等且不吞清理错误。插件 reload 可注入新注册视图。
- [ ] 测试实例复用、并发初始化、配置更新、禁用、总时限、取消、不确定投递和关闭（60 秒）；lint、构建、两个发送一次 start 的烟测。

## 实际实现与验证（2026-09-17）

- `ChannelManager` 已改为按 `(channel_id, 规范化有效配置)` 缓存常驻实例；首次使用在管理锁内创建并 start，后续发送复用；同一实例发送串行化，配置变化或旧快照产生不同缓存键，不会漂移到新目标。
- `stop` 进入幂等关闭状态，清空准入并对所有实例执行有界 stop；清理错误显式上抛。发送失败/超时保留是否已进入实例发送的 attempts 与 `delivery_uncertain` 信息。
- 验证：`tests/test_workflow_integration.py` 2 passed；相关 Ruff 与 diff 检查待本模块补充定向实例并发测试后再扩大。

### 决策依据与默认值

- 缓存键使用完整序列化 ChannelConfig 而非仅 channel_id，依据 Channel design 的“按 channel_id 与有效配置版本区分”，在当前模型没有显式 version 字段时用规范化配置快照表达版本。
- stop 超时暂用 5 秒；该值只约束资源清理，不改变发送总 timeout，后续 Lifecycle 装配可注入统一关闭预算。
