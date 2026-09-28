# 业务超时与重试边界

## 决策依据

用户明确要求超时和重试由业务内部处理：常见超时通常按 Skip 继续，不能仅因 NodeTimeoutError 让整张图暂停。本任务修正 design §1.1 和 workflow-stream-execution 的对应要求；此前 defer/Send timeout/RetryPolicy 任务保留其当时决策记录，defer 清理仍有效。

现有 SourceConfig.timeout 默认 60 秒、AIConfig.timeout 默认 600 秒且 retries 默认 5、ChannelConfig.timeout 默认 30 秒，见 src/logagent/models.py。继续使用这些已定义配置，不另设 Workflow 统一超时或重试默认值；AIService.execute 已在总预算内依据可重试性和投递不确定性有限重试，CollectorManager.collect 与 ChannelManager.send 返回带状态的业务结果。来源 on_error、分析失败策略和通知降级策略决定图是否继续。

## 实施与验证

- [x] 移除 collect/analyze/aggregate 的 Send TimeoutPolicy 和节点 RetryPolicy；继续使用原生 Send 展开动态业务项。
- [x] 图节点恢复调用 CollectorManager.collect、AIService.execute；移除此次新增的单次能力入口，避免双套接口。
- [x] Luna max 的真实 Workflow 定向测试覆盖来源 timeout 的 on_error=skip/stop，以及 AI timeout 的 analysis_failure=continue/stop；4 种策略均通过，常见超时不抛 NodeTimeoutError 中断图。
- [x] 回归真实 checkpoint 归档、deferred 清理、中断恢复、阶段重跑、不同运行配置隔离；Workflow 定向 9 项、阶段重跑 11 项和四个强退进程场景通过。
- [ ] 完成定向测试、静态检查、构建、OpenSpec 严格校验与差异审查；每条后端测试命令硬超时 60 秒。

已通过 CollectionManager 33 项和 AIService 离线配置 13 项回归；完整 Workflow 定向 9 项通过，包含普通 cancelled 业务结果与外部取消后恢复。进程强退恢复、静态检查和构建仍以最终单独执行结果为准。

通知维持原设计的未知投递不自动重发：ChannelManager.send 内部预算可返回 timeout/failed，intent 已持久化但回执未确定的恢复返回 delivery_uncertain。checkpoint/归档等设施异常继续向外传播。
