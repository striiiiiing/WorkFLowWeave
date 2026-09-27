## ADDED Requirements

### Requirement: Cron 定时运行
系统 SHALL 接收严格五段 Cron 表达式和有效 IANA 时区，按时区计算未来到期并触发启用工作流，非法配置显式失败。

#### Scenario: 保存与到期
- **WHEN** 用户保存有效 Cron 和时区并启用工作流
- **THEN** 后端保存配置，并在计算的到期时间触发一次运行

#### Scenario: 无效 Cron
- **WHEN** 表达式、时区无效或同时配置 Cron 与旧秒间隔
- **THEN** 保存失败并说明配置错误，不静默降级为手动或秒间隔

### Requirement: 兼容旧间隔
系统 SHALL 保留旧秒间隔运行语义及显式编辑状态，不自动猜测 Cron；未设置任一定时配置时仅手动运行。

#### Scenario: 旧配置与切换
- **WHEN** 打开已有秒间隔工作流
- **THEN** 明确显示旧调度模式，选择 Cron 后清除旧间隔，由用户保存新配置
