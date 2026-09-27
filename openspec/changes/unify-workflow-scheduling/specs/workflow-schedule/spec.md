## ADDED Requirements

### Requirement: 统一 Workflow 计划

系统 SHALL 通过一个 `schedule` 字段表达手动、`at`、`every` 和 `cron` 调度，并 SHALL 不再接受旧的 `interval_seconds`、`cron`、`cron_timezone` 请求字段。已持久化旧资源 SHALL 明确迁移为新格式，保留原时间语义。

#### Scenario: 迁移旧配置

- **WHEN** 加载含旧秒间隔或旧 Cron 的有效资源文件
- **THEN** 系统将其分别迁移为 `every` 或 `cron`，并原子保存新格式

#### Scenario: 旧请求字段

- **WHEN** 客户端新建或更新工作流时仍发送旧调度字段
- **THEN** 系统拒绝请求，不将其静默解释为手动运行

### Requirement: 单定时器执行

系统 SHALL 使用一个 APScheduler 实例管理全部已启用 Workflow，并通过现有运行入口提交到期任务。`at` SHALL 至多触发一次；`every` 和 `cron` 错过多个周期时 SHALL 不集中补跑。

#### Scenario: 一次性计划跨重启

- **WHEN** `at` 计划到期且已被持久消费，随后进程重启
- **THEN** 同一计划不会再次触发

#### Scenario: 多计划同时存在

- **WHEN** 多个 Workflow 分别配置 `at`、`every`、`cron`
- **THEN** 同一个计时循环按各自到期时间提交运行，执行仍使用 Workflow 的隔离快照与准入规则

### Requirement: Cron 说明和校验

系统 SHALL 用 APScheduler CronTrigger 验证严格五段表达式并计算带时区的未来到期；SHALL 用 `cron-descriptor` 给用户可读说明。无效表达式或时区 SHALL 明确报错。

#### Scenario: 新建 Cron 留空时区

- **WHEN** 前端新建或主动修改 Cron 计划
- **THEN** 系统按运行机器本地时区计算到期，预览显示该时区

#### Scenario: 旧 Cron 未保存时区

- **WHEN** 旧资源中的 Cron 未显式保存 `cron_timezone`
- **THEN** 迁移后的计划显式使用旧模型默认的 UTC，原运行时间不变

#### Scenario: 预览 Cron

- **WHEN** 用户输入有效表达式
- **THEN** 界面展示中文说明、实际采用的时区和下一次运行时间，保存后实际调度使用同一表达式与时区

#### Scenario: 星期说明

- **WHEN** Cron 表达式限定星期，包括星期范围或列表
- **THEN** `cron-descriptor` 说明中的星期名称以中文显示，与 APScheduler 实际星期语义一致

### Requirement: 工作流计划编辑

前端 SHALL 将 `at` 展示为“单次运行”，并 SHALL 为新建工作流默认选择每天 09:00。前端 SHALL 提供每小时、每天、每周和自定义 Cron 模式，由前端生成或编辑五段表达式；SHALL 不提供计划时区选项，新建或主动修改的 Cron 计划 SHALL 保存 `timezone=null` 并明确显示运行机器本地时区。

#### Scenario: 新建工作流

- **WHEN** 用户打开新建工作流页面
- **THEN** 草稿计划为每天 09:00 的五段 Cron，时区字段为 `null`

#### Scenario: 已有显式时区计划

- **WHEN** 用户仅修改工作流其他字段并保存已有显式时区 Cron 计划
- **THEN** 原时区保留并只读显示；用户主动修改该计划后，新计划使用运行机器本地时区

#### Scenario: 已有固定间隔计划

- **WHEN** 编辑已保存的 `every` 计划
- **THEN** 原间隔只读展示，保存其他字段不改变计划，界面不提供新建或修改固定间隔的控件
