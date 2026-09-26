# 任务

依据：[任务要求](../backendFix/任务要求.md)、[设计](design.md)、[行为规范](specs/workflow-schedule/spec.md)，以及用户确认“仅调度 Workflow；沿用现有运行隔离”“迁移为新 schedule 字段并移除旧字段”。

- [ ] 1.1 后端定义 `schedule` 判别联合并完成旧资源一次性迁移；移除旧字段的 API 契约。
- [ ] 1.2 后端拆分 CronStore、CronOps、CronTimer 和 executeJob，以单个 APScheduler 实例管理全部 Workflow；`at/cron` 使用 CronTrigger，`every` 使用 IntervalTrigger。
- [ ] 1.3 使用 APScheduler 验证与计算 Cron，使用 cron-descriptor 提供说明预览；移除不再使用的 croniter 依赖。
- [ ] 2.1 前端替换旧调度字段，提供三种模式配置和 Cron 说明；更新契约及编辑器测试。
- [ ] 3.1 定向测试、Ruff/类型检查、构建、OpenSpec 严格校验及真实浏览器验收。

默认值理由：`schedule=null` 对应既有未设置 `interval_seconds`/`cron` 的手动工作流；Cron 时区默认 UTC 继承现有模型默认值；周期数值无隐式默认，避免保存一个用户未确认的运行频率。一次性计划采用先消费再触发的至多一次语义，避免重启重发。

APScheduler 取舍：只使用内存作业存储，由 Workflow 资源重建；避免第二份持久化定义。`at` 使用带固定年份的 CronTrigger 实现一次性触发，`every` 使用 IntervalTrigger 保留任意正秒间隔，`cron` 使用 CronTrigger.from_crontab。
