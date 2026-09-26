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

系统 SHALL 用 `croniter` 验证严格五段表达式并计算带时区的未来到期；SHALL 用 `cron-descriptor` 给用户可读说明。无效表达式或时区 SHALL 明确报错。

#### Scenario: 预览 Cron

- **WHEN** 用户输入有效表达式与 IANA 时区
- **THEN** 界面展示说明和下一次运行时间，保存后实际调度使用同一表达式与时区
