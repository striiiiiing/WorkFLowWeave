# 通知插件归位与平台通道扩展

状态：**待用户确认，尚未进入实现**。

## Why

当前通知渠道的具体实现仍与核心运行时、旧的 `mock` 文件渠道和平台协议混在一起。这样会让核心包携带平台 SDK 细节，也会使新增渠道重复实现生命周期、发送回执和双向输入的公共逻辑。

本变更把具体通知适配器放回插件目录，并补齐六种用户需要的通知渠道：Email、QQ、微信“小龙虾”、飞书、Telegram 和本地文件。QQ、微信、飞书和 Telegram 提供双向 Agent 对话；Email 和本地文件只提供单向通知。

## What Changes

- 在 `plugins/` 下提供六个独立的 channel 插件；`src/logagent/channel/` 只保留通用协议、注册器、Manager、队列、回执和平台无关的会话模型。
- 优先使用维护方提供的 SDK/API：`aiosmtplib`、腾讯 `qq-botpy`、飞书 `lark-oapi`、`python-telegram-bot`。
- 微信“小龙虾”按当前资料解释为 OpenClaw Weixin 通道；Python 插件使用受支持的 OpenClaw/Tencent iLink 桥接或 sidecar，不在 LogAgent 内重写 iLink 协议。
- 本地文件渠道从旧的 `mock` 语义改为正式的文件记录渠道。拟采用追加式 UTF-8 JSON Lines，每条通知对应一条记录；旧能力名是否迁移为 `file` 需用户确认。
- Email 继续使用现有 `aiosmtplib` SMTP 出站实现，只发送通知，不增加 IMAP/POP 入站。
- 删除新资源初始化时的采集器预配置和旧 `default_file`/`mock` 通知种子；不删除用户已经保存的来源或渠道，兼容迁移另列任务。

## Capabilities

- `notification-plugins`：插件边界、六种渠道的能力矩阵、配置和投递语义。
- `notification-delivery`：Email、本地文件及四种双向平台适配器的发送、入站和回执约束。
- `starter-resources`：新资源文档不再自动创建采集器或旧文件通知配置。

## Scope

本变更包含插件清单、插件依赖、渠道配置 schema、SDK 生命周期适配、入站消息归一化、单向发送和定向测试。双向消息必须继续经过既有唯一 `ChannelManager` 和 Agent 处理端口，插件不能直接调用模型或 Workflow。

## Non-goals

- 不把 Email 扩展成收件箱、IMAP 或 POP 客户端。
- 不在核心层实现 QQ、微信、飞书或 Telegram 的协议。
- 不把 Workflow 注册成双向消息消费者；双向渠道只绑定 Agent。
- 不为已存在的用户资源静默删除来源、凭据或历史回执。
- 不在用户确认前修改 `design.md`、实现代码或锁文件。

## Approval blockers

请重点确认以下方案后再开始实现：

1. **Email**：是否接受仅 SMTP 出站、`aiosmtplib`、TLS 显式配置、凭据走 `CredentialResolver`，以及 DATA 响应丢失时标记投递不确定且不自动重试。
2. **本地文件**：是否接受正式能力名 `file`（旧 `mock` 资源做显式迁移）、追加式 JSONL、相对 `data_dir` 路径、写入后 `flush`，以及默认不 `fsync`。如果需要人类可读纯文本、强制 `fsync` 或保留 `mock` 名称，请在确认时指定。
3. **微信“小龙虾”**：是否确指 OpenClaw Weixin/Tencent iLink 通道；如果是另一个微信项目，需要替换桥接方案和依赖。

## References

- [OpenSpec 变更约定](../../README.md)
- [统一 ChannelManager 设计](../redesign-agent-channel-manager/design.md)
- [腾讯 Botpy](https://github.com/tencent-connect/botpy)
- [飞书 Python SDK](https://github.com/larksuite/oapi-sdk-python)
- [python-telegram-bot](https://docs.python-telegram-bot.org/)
- [aiosmtplib](https://aiosmtplib.readthedocs.io/)
- [OpenClaw Weixin 通道说明](https://docs.openclaw.ai/zh-CN/channels/wechat.md)
