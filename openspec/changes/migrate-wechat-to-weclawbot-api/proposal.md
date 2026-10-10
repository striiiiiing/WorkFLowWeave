# 微信迁移至 WeClawBot-API

## Why

用户指出当前微信插件安装完整 OpenClaw 宿主不符合极小化要求：本地 node_modules 实测约 851 MB，腾讯微信插件 npm 包解包仅 696,653 字节。2026-10-07 用户指定改用 https://github.com/Cp0204/WeClawBot-API ，同时在前端给出第三方风险警示。

## What Changes

- 使用用户指定的独立 WeClawBot-API 服务，LogAgent 经 HTTP 发送微信通知，移除微信插件的 OpenClaw/Node 依赖。
- 频道编辑页明确标出第三方项目、凭据与消息处理风险、部署与平台可用性风险，并链接上游项目。
- 以实际公开 API 为边界：核对扫码和消息接收能力，不能假设不存在的 HTTP 接口。
- 配置与文档明确服务地址、bot_id、api_token 获取方式和微信首次消息/10 条回复限制。
- 后续自有实现参考用户指定的 https://cloud.tencent.com/developer/article/2651968 ；本轮不把该文章当作腾讯对第三方项目的认可或服务保证。

## Evidence

上游源码核对版本：c8851d44f4c31ea814357308f2cf438ca5e588f5。

- README 声称二进制及内存约 10 MB，独立 Go 服务，无 OpenClaw 运行时；本轮尚未实测该体积。
- main.go:startAPIServer 仅公开 /bots/{bot_id}/messages 和 /typing，支持 Bearer api_token。
- /messages 仅接受 text，发送目标来自服务保存的 ilink_user_id/context_token，不提供任意 target_id。
- QR 登录在终端 /login 或 bot 命令中，凭据持久化到 config/auth.json；没有网页登录 HTTP API。
- 上游内部轮询微信消息，但只在终端输出，没有供 LogAgent Agent 消费的消息回调/拉取 API。
- 文章 HTTP 请求遇到腾讯云防护页面，本轮只记录用户提供的链接，不推断文章内容。

既有网页扫码/双向对话需求与上游公开能力之间的取舍已向用户询问；后续设计和实施记录必须体现最终选择。
