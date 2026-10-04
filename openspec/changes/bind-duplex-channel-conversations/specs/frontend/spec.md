# 双向渠道绑定管理

## ADDED Requirements

### Requirement: 从双向渠道实例绑定对话

前端 SHALL 在双向渠道实例处提供当前对话的查询、选择、更换和解绑，初始显示未绑定。前端 SHALL NOT 将该入口放为 Agent 对话选择渠道或全局默认渠道设置。

#### Scenario: 用户绑定现有对话

- **WHEN** 用户在一个双向渠道实例的管理页面选择已有 Agent 对话并保存
- **THEN** 页面显示该实例的实际绑定结果
- **AND** 重新打开页面仍显示持久化的绑定

#### Scenario: 单向渠道实例

- **WHEN** 用户编辑 Email 或 file 实例
- **THEN** 页面不提供 Agent 对话绑定入口

#### Scenario: 解除绑定

- **WHEN** 用户解除一个双向实例的对话绑定
- **THEN** 页面显示未绑定
- **AND** 不修改 Agent 对话本身或为其选择另一个渠道

### Requirement: 绑定对话仍支持 Web 查看与调试

系统 SHALL 允许从 Web 查看和调试被渠道绑定的 Agent 对话，使用同一个 session 和唯一事件日志；渠道绑定 SHALL NOT 使对话从 Web 不可见。

#### Scenario: 查看平台消息产生的结果

- **WHEN** 绑定实例收到消息后，用户从 Web 打开该对话
- **THEN** 用户可查看同一对话的历史、状态与事件
- **AND** 不复制另一个 Web 对话，也不因读取而再次向平台发送

#### Scenario: 从绑定入口打开对话

- **WHEN** 用户在渠道实例的绑定信息处打开对话
- **THEN** 前端进入对应 Agent 对话的 Web 页面
- **AND** Web 调试指令仍使用已有 Agent 指令端口和取消语义
