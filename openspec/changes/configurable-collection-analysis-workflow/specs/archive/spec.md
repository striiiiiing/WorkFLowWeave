## Purpose

保存每次 Workflow 的运行事实、确定配置和可选阶段内容，为结果查询、历史采集和中断恢复提供可核验的数据，并明确指出缺失或不可恢复的范围。

## ADDED Requirements

### Requirement: 阶段保存与可恢复范围

系统 SHALL 区分持久运行记录和可选内容备份，支持配置备份阶段与有效期，并报告关闭、缺失、损坏、过期和写入失败。

#### Scenario: 备份关闭

- **WHEN** 关闭内容备份后完成运行
- **THEN** 仍能查询运行状态，并明确说明无法恢复的阶段

#### Scenario: 失败策略

- **WHEN** 阶段备份写入失败
- **THEN** 标记不完整并按 stop 或 continue 策略执行，不能宣称完整恢复

### Requirement: 历史与完整性

系统 SHALL 按 Workflow、时间和数量查询已有 session，验证读取内容完整性，并在重启后识别中断运行。

#### Scenario: 内容被修改

- **WHEN** 备份文件内容与保存校验值不符
- **THEN** 返回损坏错误而非使用该内容

#### Scenario: 服务中断

- **WHEN** 启动时发现未正常结束的运行
- **THEN** 将运行标为 interrupted，保留成功阶段和恢复材料
