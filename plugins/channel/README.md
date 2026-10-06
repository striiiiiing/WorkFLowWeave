# 通知渠道插件

`email`、`file`、`qq`、`wechat_openclaw`、`feishu` 和 `telegram` 都是独立插件，核心包只提供通用 `ChannelManager` 和协议。

安装平台 SDK 时按需选择 `uv sync --extra email`、`--extra qq`、`--extra feishu`、`--extra telegram` 或 `--extra channels`。Email 使用 `aiosmtplib` 仅发送 SMTP 通知；file 使用标准库 `logging.FileHandler` 追加 UTF-8 日志。QQ 使用腾讯官方 SDK，飞书使用飞书官方 SDK，Telegram 使用成熟的社区 SDK `python-telegram-bot`。微信插件自带 Node bridge，调用腾讯官方 OpenClaw Weixin 包，通过 JSON Lines 与 Python 插件通信。

启用插件后，在资源配置中使用插件声明的能力名。Email 和 file 只有 `notification`；其余四个渠道还声明 `conversation`，双向输入统一交给核心 `ChannelManager`。

双向渠道按资源实例绑定一个 Agent 对话；同一能力可以配置多个实例。启用 Agent 接收后，在渠道实例管理处选择已有对话，或从平台发送 `/resume <对话ID>` 修改绑定。未绑定的普通消息明确报错，不自动创建对话；`/new` 可显式创建并绑定新对话。同一实例不同好友/群的消息进入同一对话，回复仍回到原消息地址。

绑定的对话仍可通过 Web 查看和调试。解绑或改绑会使旧排队输入与在途输出失效，不转投新对话。接收回调入队后返回，停止等指令继续按优先级处理。Email/file 只用于 Workflow 通知；Workflow 向双向插件发送通知同样不要求 Agent 绑定。

## Email 与文件

Email 资源配置 `host`、`port`、`sender`、`recipient`；`tls` 默认 `starttls`，465 端口可显式使用 `implicit`。认证时配置 `username` 和凭据引用 `password`，收件人支持 Workflow 覆盖。仅收到 SMTP DATA 成功响应才记为成功；DATA 响应丢失记为投递不确定，不隐式重发。

file 配置 `path`（相对 `data_dir`），自动建立父目录，追加 UTF-8 日志。每条记录含 UTC 时间、channel/session/output ID、标题和正文，flush 后成功；写入、flush 和关闭失败显式报告。旧存量 `mock` 文件渠道在持久化读取时迁移为 `file`，保留资源 ID、路径和 Workflow 绑定。新建资源不再接受 `mock`。

## QQ、飞书与 Telegram

| 插件 | 账号配置 | 单向通知目标 |
| --- | --- | --- |
| qq | `app_id`、`client_secret` 凭据引用 | `target_kind` 为 `c2c/group/guild/dm`，`target_id` 为对应好友、群、频道或私信会话 ID |
| feishu | `app_id`、`app_secret` 凭据引用 | `target_kind` 为 `chat_id/open_id/user_id/email`，配套 `target_id` |
| telegram | `token` 凭据引用 | `chat_id` |

凭据引用例如 `{"kind":"env","name":"QQ_BOT_SECRET"}`；资源设置 `agent_enabled=true` 开启双向接收，回复使用入站消息的原路由。QQ 与飞书需在平台后台启用机器人对应事件和消息权限；Telegram 使用 long polling，同一 Bot 不应同时运行另一个 polling/webhook 接收端。消息发送仍受平台自身权限和会话限制。

飞书固定 `lark-oapi==1.7.3`：该版本没有公开异步 WebSocket 停止接口，插件集中适配其生命周期并管理共享 SDK 线程；升级版本前需通过 SDK contract 测试。

## 微信 OpenClaw

依赖固定为腾讯 `@tencent-weixin/openclaw-weixin@2.4.9` 和宿主 `openclaw@2026.8.1`。宿主需要 Node `>=22.22.3 <23`、`>=24.15.0 <25` 或 `>=25.9.0`。从仓库部署插件并安装其独立依赖：

```bash
cd plugins/channel/wechat_openclaw
npm ci --ignore-scripts --no-audit --no-fund
```

用腾讯官方登录流程创建本地账号（自定义状态目录时，为下列命令和插件配置使用相同的 `OPENCLAW_STATE_DIR`）：

```bash
npx openclaw plugins install "@tencent-weixin/openclaw-weixin@2.4.9"
npx openclaw config set plugins.entries.openclaw-weixin.enabled true
npx openclaw channels login --channel openclaw-weixin
```

扫码确认后，从状态目录的 `openclaw-weixin/accounts.json` 读取账号 ID，在 WorkFLowWeave 渠道 `options` 配置 `account_id`；可选 `state_dir` 指向该状态目录，`command` 可指定 Node 可执行文件路径，默认 `node`。通知的 `target_id` 为微信对端 ID，可由 Workflow 覆盖；回复从官方 SDK 存储复用对端 context token，因此需先收到对端消息建立上下文。

目前腾讯 SDK 支持微信私信。同一账号应只由一个进程接收：使用 WorkFLowWeave 接收时，停止该账号在 OpenClaw Gateway 的轮询。入站由 Manager 持久化受理后才确认并推进官方游标；关闭时中止长轮询。未登录、依赖或 Node 版本错误会显式失败。bridge 复用固定版本包内账户、收发、上下文和游标模块；升级依赖时需重新验证这些模块契约。

平台凭据认证后的真实联网验收需要用户自己的账号；仓库测试使用 SDK contract 和本地进程，避免发送真实通知。
