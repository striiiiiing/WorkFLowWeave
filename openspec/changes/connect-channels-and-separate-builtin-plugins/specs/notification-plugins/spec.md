## MODIFIED Requirements

### Requirement: 官方 SDK 优先

QQ SHALL 使用腾讯 qq-botpy；飞书 SHALL 使用用户确认的官方 lark-channel-sdk；Telegram SHALL 使用 python-telegram-bot；Email SHALL 使用 aiosmtplib。平台 SDK 回调 SHALL 归一化输入并交给唯一 ChannelManager，不直接执行 Agent 或 Workflow。飞书鉴权与 SDK 阻塞 I/O SHALL 不阻塞应用事件循环。

#### Scenario: SDK 回调进入统一队列

- **WHEN** 平台 SDK 接收一条消息
- **THEN** 消息归一化后等待 Manager 实际受理
- **AND** SDK 回调不创建第二个 Manager 或模型循环
