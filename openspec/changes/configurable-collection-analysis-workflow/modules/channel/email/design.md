# 邮件渠道设计

[Channel 网关](../design.md) · [ChannelConfig 契约](../../../contracts/data-models.md#24-channel-配置)

注册名为 email，能力为 notification。一个实例对应一个 SMTP 服务和一个收件人；要发给多个收件人，配置多个实例，使每条回执含义明确。

## options

| 字段 | 类型及约束 | 解释 |
| --- | --- | --- |
| host | 非空字符串，必填 | SMTP 主机。 |
| port | 1–65535 的整数，必填 | 显式填写，避免推测服务配置。 |
| sender | 单个邮箱地址，必填 | SMTP 信封发件人及 From。 |
| recipient | 单个邮箱地址，必填 | SMTP 信封收件人及 To。 |
| tls | none/starttls/implicit，默认 starttls | 显式连接方式，协商失败报告错误。 |
| username | 字符串或 null，默认 null | SMTP 认证用户。 |
| password | Credential 或 null，默认 null | 与 username 成对提供；不认证的本地 relay 可都为空。 |

未知字段拒绝；地址不能含 CR/LF。超时和 enabled 使用 ChannelConfig 公共字段，不重复放入 options。标题直接使用 Notification.title，正文使用 Notification.text，无额外模板系统。

## 一次投递

ChannelManager 按原快照配置创建实例。start 准备异步 SMTP 客户端，send 连接、按 tls 配置协商、可选认证，构造 UTF-8 text/plain MIME 并提交一次消息，stop 关闭连接。适配器自身的网络操作设时限，不重连补发。

message ID 可以由 session_id/output_id/channel_id 稳定派生以便诊断，但 SMTP 不保证据此去重。正文不包含额外实现信息，输出关联由回执和日志记录。

连接/认证/收件人拒绝时报告明确失败；DATA 正文完成后服务器肯定接受才成功。提交后响应丢失或取消时标记 delivery_uncertain，服务不自动再次提交。SMTP 接受只表示服务器受理，不代表到达收件箱或被阅读。

## 验证要点

使用本地 SMTP 测试服务检查 MIME、地址、标题/正文、认证拒绝、TLS 错误、DATA 后断开及超时。记录实际提交次数，确认一次 send 没有隐式重试；已成功提交后的断连清理不覆盖成功回执。
