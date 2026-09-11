## Purpose

将 Workflow 输出按用户顺序投递到一个或多个通知目标，隔离平台故障与配置错误，并通过能力区分让单向工作流和后续双向会话能各自保持清晰的职责。

## ADDED Requirements

### Requirement: 通知能力与插件隔离

系统 SHALL 发现 channels 插件并注册能力，首版提供追加文件和 SMTP 邮件通知；Workflow 不依赖接收循环。

#### Scenario: 重复或坏插件

- **WHEN** 一个插件声明重复 channel
- **THEN** 报告错误且保留其他有效 channel

#### Scenario: 能力不符

- **WHEN** Workflow 引用了不支持通知的 channel
- **THEN** 保存前返回校验错误

### Requirement: 有序投递与失败记录

系统 SHALL 保持输出和目标的配置顺序，使用有限重试与超时，独立保存每个输出和目标的投递状态。

#### Scenario: 部分目标失败

- **WHEN** 邮件失败而文件目标成功
- **THEN** 记录各自状态且仍保存分析结果

#### Scenario: 文件并发追加

- **WHEN** 同一文件同时接收多条通知
- **THEN** 每条消息完整写入，不交错破坏内容

#### Scenario: 停止服务

- **WHEN** 关闭拥有活动 channel 的服务
- **THEN** 有序关闭连接并回收后台任务
