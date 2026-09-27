## ADDED Requirements

### Requirement: Agent 双向渠道
系统 SHALL 使 Web、QQ 和本地测试渠道共用 Agent 命令与事件入口，双向消息消费者 SHALL 仅为 Agent。

#### Scenario: 跨渠道对话与停止
- **WHEN** 渠道提交普通消息或 stop 指令
- **THEN** 普通消息进入绑定 Agent 会话，stop 独立取消活动轮次并产生可见结果

### Requirement: 单向兼容
声明 notification 能力的双向适配器 SHALL 可由 Workflow 等调用者通过既有 send 契约发送通知。

#### Scenario: 未启用接收
- **WHEN** agent_enabled=false 且调用 send
- **THEN** 通知按配置目标发送，不创建 Agent 会话或连接接收循环

### Requirement: 会话与回复隔离
系统 SHALL 固定来源身份和回复地址，持久化外部会话绑定，并拒绝跨对话 resume 与同一请求 ID 的不同内容。

#### Scenario: 重复消息与服务重启
- **WHEN** 同一来源消息被重复投递或服务重启后收到下一条消息
- **THEN** 已处理消息不重复执行，新消息继续既有绑定，回复始终发送至原请求地址
