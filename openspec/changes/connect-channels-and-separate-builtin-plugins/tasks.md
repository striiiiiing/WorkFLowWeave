# 待完成任务

首条消息引导、内置与用户插件分离、飞书官方 Channel SDK 和异步 I/O 修正已有实现及自动化记录；外部账号收发不能计为全部通过。

依据：[提案](proposal.md)、[设计](design.md)、[渠道验收证据](../../../artifacts/channels/2026-10-09/README.md)。

- [ ] 1.1 使用 QQ、飞书和 Telegram 的真实首条私聊事件验证目标获取、精确回复「成功连接」、单向接收收尾和后续通知；等待消息或仅 connected 不计为闭环。
- [ ] 1.2 复验飞书 lark-channel-sdk 的首次 WebSocket 连接、私聊、回复和单向通知，区分 SDK 自动化与真实账号证据。
- [ ] 1.3 核对 QQ 实例平台码 100016 与 Telegram chat not found 的配置结果，不将平台拒绝当作已修复。
- [ ] 1.4 完成微信本人扫码、登录持久化与真实收发，验证 context_token 限制；QR 请求/取消通过不能代替登录。
