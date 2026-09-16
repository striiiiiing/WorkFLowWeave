# Lifecycle任务

状态：待执行，完成后在本文件记录提交前验证结果。

依据：[Lifecycle设计](./design.md)、[总设计](../../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：配置、AI、Channel/Mock/Email、Workflow、Collection；API 通过工厂注入，最终 HTTP 生命周期由 Interaction 接线。

- [ ] 装配 SystemConfig、CredentialManager、JSON ResourceStore、LangGraph SQLite checkpointer、SessionStore 和只读 SessionView；初始化失败保留明确错误并逆序清理，不开放运行准入。
- [ ] 注册 history/logs/mock Collector 和 email/mock Channel，再扫描外部插件；只读注册视图及语义校验器按依赖注入，完成引用校验。插件缺失可降级；启动不访问实际来源/模型/通知平台。
- [ ] 装配 Workflow 与 IntervalTrigger，定时/手动入口共用容量、enabled、快照和取消；资源更新后重建未来计划，不补跑错过触发。
- [ ] resources reload 原子发布；plugins reload 原子关闭准入并暂停定时，活动冲突拒绝后恢复准入；无活动时关闭旧 owner 实例再重新注册、注入新视图，失败保留诊断。
- [ ] 健康查询仅汇总本地状态、accepting_runs 与诊断，必要依赖不可用禁止运行，可选插件错误 degraded；后续成功检查可恢复状态。
- [ ] 关闭先禁止新运行/定时，再有界收束所有session，释放客户端/渠道/插件，最后 SessionStore/checkpointer；日志采用标准 logging 的逐行 JSON、轮转和脱敏，供 logs Collector 读取。
- [ ] 单测启动失败清理、定时重排/禁用/容量、reload 冲突/降级恢复、幂等关闭（60秒），lint、构建、临时配置完整装配烟测。
