# 设计

## 配置与迁移

`WorkflowDefinition.schedule` 是唯一持久化计划配置，`null` 表示仅手动运行。非空值按 `type` 区分：`at` 使用带时区 ISO 时间，`every` 使用正数 `every_seconds`，`cron` 使用严格五段 `expression` 与可选 IANA `timezone`。Cron 未指定时区时由 APScheduler 按运行机器本地时区解释。旧 `interval_seconds`、`cron`、`cron_timezone` 从模型和前端请求中移除。

已有资源文件中旧字段在加载时执行一次明确的版本迁移：旧间隔转为 `every`，旧 Cron 与时区转为 `cron`，没有计划转为 `null`。迁移校验成功后原子发布新格式；字段冲突、无效表达式或时区明确报错，不推断为手动计划。后续 API 不再接受旧字段。后端默认 `schedule=null` 延续未设计划时仅手动运行；新建工作流的前端草稿默认每天 09:00，保存为 `schedule={type: "cron", expression: "0 9 * * *", timezone: null}`。旧模型的 `cron_timezone` 默认是 UTC，因此旧 Cron 即使未显式保存时区，迁移后也要写入 UTC，保持已有执行时间；新 Cron 留空才使用机器本地时区。

## 调度边界

原始任务要求借用 OpenClaw 的 `CronStore / CronOps / CronTimer / executeJob` 职责划分；后续明确采用 APScheduler，故不要求机械复制这四个类。现有 `ResourceStore` 保存 Workflow `schedule` 并处理计划 CRUD，单个 `AsyncIOScheduler` 管理运行作业与计时，作业回调调用现有 `WorkflowService.trigger(workflow_id)`。只保留有实际代码复杂度需要的辅助函数或类。

APScheduler 只使用内存作业存储，启动时从 Workflow 资源重建计划，避免两份持久化计划。`at` 对应限定到指定年月日时分秒的 APScheduler `CronTrigger`，到期先持久消费计划，再尝试触发，保证进程重启后不会重复执行；准入失败显式记录，不静默补发。`every` 对应 `IntervalTrigger`，允许任意正秒间隔。`cron` 对应 APScheduler `CronTrigger.from_crontab`，显式时区使用配置值，否则使用 APScheduler 的本地时区默认。不能表达为 Cron 的任意间隔仍保持 Interval 语义。前端的每小时、每天、每周和自定义均保存为 `cron`，后端按持久化的 `at/every/cron` 计划管理 Cron 与 Interval 两类作业。

错过多个周期只触发一次，随后从当前时间计算未来到期。禁用的 Workflow 不自动执行；重新启用后从当前时刻计算计划。资源变化只更新发生变化的作业，不无故重置未变化的周期截止时间。APScheduler 的执行函数只提交 `WorkflowService.trigger`，不得在调度器内复制 Workflow 运行逻辑。

Cron 说明由 `cron-descriptor` 生成，APScheduler 的 `CronTrigger` 是表达式合法性和下一次时间的权威。`cron-descriptor` 的星期名读取进程 locale；后端将说明中的星期名转换为中文，不修改进程全局 locale。后端提供只读预览接口返回说明、所用时区与下一次到期，前端编辑 Cron 时展示；预览失败显示明确错误，不代替保存校验。

前端将 `at` 命名为“单次运行”，提供时间选择；将 `cron` 表现为每小时、每天、每周和自定义，预设由前端生成五段表达式。新建及主动修改的 Cron 计划统一写入 `timezone=null`，界面不提供计划时区选择，明确显示“运行机器本地时区（不指定）”以及预览实际采用的时区。既有显式时区计划保留原值并只读说明，避免仅修改工作流其他字段就改变既定运行时刻；用户主动修改该计划后改用机器本地时区。已存 `every` 计划只读保留，界面不再提供新增或编辑固定间隔的控件。未路由的旧编辑视图也移除该控件。

## 验证重点

覆盖旧配置迁移成功/冲突及旧 UTC 默认、`at` 重启后不重复、`every` 跳过积压、新 Cron 本地时区默认与显式时区兼容、无效表达式、单 APScheduler 实例、资源更新作业、触发准入失败、中文星期说明预览、新工作流默认每天及四种 Cron 选项保存与真实浏览器交互。
