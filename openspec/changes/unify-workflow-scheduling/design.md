# 设计

## 配置与迁移

`WorkflowDefinition.schedule` 是唯一计划配置，`null` 表示仅手动运行。非空值按 `type` 区分：`at` 使用带时区 ISO 时间，`every` 使用正数 `every_seconds`，`cron` 使用严格五段 `expression` 和有效 IANA `timezone`。旧 `interval_seconds`、`cron`、`cron_timezone` 从模型和前端请求中移除。

已有资源文件中旧字段在加载时执行一次明确的版本迁移：旧间隔转为 `every`，旧 Cron 与时区转为 `cron`，没有计划转为 `null`。迁移校验成功后原子发布新格式；字段冲突、无效表达式或时区明确报错，不推断为手动计划。后续 API 不再接受旧字段。默认 `schedule=null` 延续未设计划时仅手动运行；Cron 默认时区沿用现有 UTC 约定，迁移时保留原时区。

## 组件边界

| 组件 | 职责 |
| --- | --- |
| `CronStore` | 从资源存储加载、保存 Workflow 的权威 `schedule`；不维护第二份计划定义。一次性计划的消费与资源更新在同一持久化边界完成。 |
| `CronOps` | `add / remove / update` 计划操作，验证工作流存在与更新条件，调用 `CronStore`。 |
| `CronTimer` | 持有一个 `AsyncIOScheduler` 实例；资源变化时更新其作业，全部 Workflow 共用该调度器的计时循环。 |
| `executeJob` | 到期后调用现有 `WorkflowService.trigger(workflow_id)`，复用快照、容量、取消和隔离运行语义。 |

APScheduler 只使用内存作业存储，启动时从 Workflow 资源重建计划，避免两份持久化计划。`at` 对应一次性 `DateTrigger`；到期先持久消费计划，再尝试触发，保证进程重启后不会重复执行；准入失败显式记录，不静默补发。`every` 对应 `IntervalTrigger`，允许任意正秒间隔。`cron` 使用基于 `croniter` 的 APScheduler 触发器，保持五段表达式、时区与实际下次触发的语义一致；不把任意间隔或一次性任务硬转为 Cron 表达式。三个前端模式在后端都归一为调度器作业，但触发器类型不同。

错过多个周期只触发一次，随后从当前时间计算未来到期。禁用的 Workflow 不自动执行；重新启用后从当前时刻计算计划。资源变化只更新发生变化的作业，不无故重置未变化的周期截止时间。APScheduler 的执行函数只提交 `WorkflowService.trigger`，不得在调度器内复制 Workflow 运行逻辑。

Cron 说明由 `cron-descriptor` 生成，`croniter` 仍是表达式合法性和下一次时间的权威。后端提供只读预览接口返回说明与下一次到期，前端编辑 Cron 时展示；预览失败显示明确错误，不代替保存校验。前端用 `at` 时间选择、`every` 数值与单位、Cron 表达式与时区控件，保持已有编辑器布局。

## 验证重点

覆盖旧配置迁移成功/冲突、`at` 重启后不重复、`every` 跳过积压、Cron 时区和无效表达式、单 APScheduler 实例、资源更新作业、触发准入失败、说明预览、前端三种模式保存与真实浏览器交互。
