# 任务

依据：[任务要求](../backendFix/任务要求.md)、[设计](design.md)、[行为规范](specs/workflow-schedule/spec.md)，以及用户确认“仅调度 Workflow；沿用现有运行隔离”“迁移为新 schedule 字段并移除旧字段”“新 Cron 默认机器本地时区，采用 APScheduler 简化组件”。

- [x] 1.1 后端定义 `schedule` 判别联合并完成旧资源一次性迁移；移除旧字段的 API 契约。
- [x] 1.2 后端复用 ResourceStore 持久化计划，以单个 APScheduler 实例管理全部 Workflow；`at/cron` 使用 CronTrigger，`every` 使用 IntervalTrigger，到期调用 WorkflowService.trigger。
- [x] 1.3 使用 APScheduler 验证与计算 Cron，使用 cron-descriptor 提供说明预览；移除不再使用的 croniter 依赖。
- [x] 2.1 前端替换旧调度字段，提供单次运行与每小时、每天、每周、自定义 Cron 配置和说明；更新契约及编辑器测试。
- [x] 2.2 依据本次用户修订，将 `at` 改称“单次运行”；新建草稿默认每天 09:00；移除计划时区选项，前端新建或修改 Cron 时保存 `timezone=null`；移除未路由旧视图的固定间隔控件，并更新定向测试。
- [x] 2.3 依据本次用户反馈，修正 `cron-descriptor` 中文说明中的英文星期名称，覆盖后端描述与预览测试。
- [x] 3.1 定向测试、Ruff/类型检查、构建、OpenSpec 严格校验及真实浏览器验收。

默认值理由：`schedule=null` 对应既有未设置 `interval_seconds`/`cron` 的手动工作流；新 Cron 的 `timezone=null` 使用 APScheduler 的运行机器本地时区，遵从用户本次修正；旧 Cron 未显式保存时区时按旧模型默认 UTC 迁移，避免改变已有计划；周期数值无隐式默认，避免保存一个用户未确认的运行频率。一次性计划采用先消费再触发的至多一次语义，避免重启重发。

APScheduler 取舍：只使用内存作业存储，由 Workflow 资源重建；避免第二份持久化定义。原要求中的四个 OpenClaw 式组件是职责参考，采用 APScheduler 后不强制拆成四个类。`at` 使用带固定年份的 CronTrigger 实现一次性触发，`every` 使用 IntervalTrigger 保留任意正秒间隔，`cron` 使用 CronTrigger.from_crontab。

后端实施依据与边界（设计保持不变；依据本次用户确认及主工作区任务原始要求）：

- 资源格式升级为 version 2；构造加载和热重载均先迁移、整体验证，再复用 ResourceStore 的原子发布。API 保持严格模型；只有持久化边界接受旧字段，恢复既有 session 时同样转换旧快照中的计划。
- `at` 使用锁内条件消费，只在启用状态且原 schedule 仍匹配时清空。APScheduler CronTrigger 精度为秒，因此有微秒的输入向上取整，不提前运行；停机或禁用期间已经到期且尚未消费的计划，在启动或重新启用后提交一次。消费失败和运行准入失败明确记日志，不自动补发已消费计划。
- 依据设计“错过多个周期只触发一次，随后从当前时间计算未来到期”，启用 coalesce，并在 every 回调准入前将下一次到期设为当前时间加间隔；未变化的作业保持截止时间。调度器生命周期暂停保留作业，由 APScheduler 合并错过的周期。
- 旧 croniter 将数字星期 0/7 解释为周日，APScheduler 将 0 解释为周一；迁移先展开星期范围与步进，再写星期名称以保留原运行时间。旧表达式同时限制日期和星期时，旧 OR 与新 CronTrigger AND 语义不能等价，故明确报错并保留原文件，要求显式调整计划；不静默改时刻。其他新引擎不支持的旧语法也由校验明确拒绝。
- Cron 预览接口为 `POST /api/workflows/cron/preview`，请求 expression 与可选 timezone，响应 description、timezone、next_run_at；预览与保存、执行共享 CronTrigger 校验。cron-descriptor 中文模板的星期名称取决于运行系统 locale，2.3 以该库实际使用的 `calendar.day_name` 名称为边界将输出转换为中文，不修改全局 locale。

2.2 默认值与兼容依据：[设计](design.md)和[行为规范](specs/workflow-schedule/spec.md)按本次用户确认更新。每天 09:00 沿用前端已实现的“每天”预设初值 `0 9 * * *`，避免新建页面显示一种计划却保存另一种；后端 `schedule=null` 仍代表旧资源或 API 未设计划的手动运行。旧显式 IANA 时区源于迁移保时刻规则，因此仅在用户主动修改计划时清为 `null`，避免保存名称等无关字段后悄然改变运行时间。已存 `every` 仍由后端执行，但前端不再提供编辑控件。

验证记录：每批后端 pytest 均以 `timeout 60s` 执行。模型/调度/资源迁移/API 批次 76 项通过；补充迁移和旧快照恢复后，调度/资源/恢复/生命周期批次 110 项通过；最终生命周期/API/调度/恢复批次 96 项通过（批次有重叠）；本次星期说明及交互定向批次 40 项通过。`ruff check` 改动文件、`uv build`、前端定向 Vitest 6 项、完整 Vitest 224 项（`--maxWorkers=2`）、`vue-tsc --noEmit`、Prettier、前端构建、架构检查和 OpenSpec 严格校验均通过。真实 ApplicationLifecycle 启停与 HTTP Cron 预览冒烟通过；浏览器在 5179 前端及 14311 后端验证了中文星期、无时区选项、移动端宽度及保存的 `timezone=null`。仓库未配置独立 Python 类型检查器。
