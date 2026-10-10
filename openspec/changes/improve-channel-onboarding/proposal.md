# 频道配置说明与网页微信登录

## Why

用户在频道插件配置中遇到以下问题：QQ 机器人需要首次互动，当前程序不能自动代替用户完成，导致仅填配置无法使用；Email 的 SMTP 信息来源、服务器格式、端口差异、发件人/收件人语义及授权码均缺少说明；微信只有命令行登录，网页不能直接提供二维码链接扫码；微信 iLink 每条用户消息的 context_token 最多回复 10 条消息的硬限制未说明；文件 path 缺少实际可用示例。

2026-10-07 用户明确要求微信在网页内直接扫码登录，作为该插件的特别处理，并要求先记录 OpenSpec 再实现。

## What Changes

- 保留 QQ 插件，明确用户必须完成首次互动，平台 ID 与普通 QQ 号码不同，后续发送仍受平台规则限制。
- Email 参数逐项解释，说明一般从邮箱的 POP3/IMAP/SMTP/Exchange/CardDAV 服务获取信息，各项备注包含 Gmail 示例；password 的界面名称改为授权码，保留已存配置键。
- 微信渠道编辑页增加扫码登录、二维码链接、数字确认、刷新/取消、成功回填账号 ID；Token 自动存入官方本地账号文件。
- 明确微信每个 context_token 最多回复 10 条消息，给出文件 path 的可用相对路径示例。

## Capabilities

### New Capabilities

- `channel-onboarding`: 频道配置说明、官方 SDK 网页登录与本地 Token 复用。

## Impact

涉及频道插件 schema、微信 Node 登录桥接、可选插件登录接口及 HTTP 生命周期、频道编辑 UI 和契约测试。保留原通知/Agent 唯一 Manager 与既有凭据存储，不复制 iLink 登录协议，不自动发送首次平台消息。原有 proposal/design 保持不变。
