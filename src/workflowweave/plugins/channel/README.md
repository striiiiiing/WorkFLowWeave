# 通知渠道插件

`email`、`file`、`qq`、`wechat_openclaw`、`feishu` 和 `telegram` 都是独立插件，核心包只提供通用 `ChannelManager` 和协议。

安装平台 SDK 时按需选择 `uv sync --extra email`、`--extra qq`、`--extra feishu`、`--extra telegram` 或 `--extra channels`。Email 使用 `aiosmtplib` 仅发送 SMTP 通知；file 使用标准库 `logging.FileHandler` 追加 UTF-8 日志。QQ 使用腾讯官方 SDK，飞书使用飞书官方 SDK，Telegram 使用成熟的社区 SDK `python-telegram-bot`。微信插件使用轻量 Node SDK [corespeed-io/wechatbot](https://github.com/corespeed-io/wechatbot)，不安装完整 OpenClaw。

启用插件后，在资源配置中使用插件声明的能力名。Email、file 只有 `notification`；微信、QQ、飞书、Telegram 还声明 `conversation`，双向输入统一交给核心 `ChannelManager`。

双向渠道按资源实例绑定一个 Agent 对话；同一能力可以配置多个实例。启用 Agent 接收后，在渠道实例管理处选择已有对话，或从平台发送 `/resume` 查看历史，再发送 `/resume <对话ID>` 修改绑定。未绑定的普通消息明确报错，不自动创建对话；`/new` 可显式创建并绑定新对话。同一实例不同好友/群的消息进入同一对话，回复仍回到原消息地址。

绑定的对话仍可通过 Web 查看和调试。解绑或改绑会使旧排队输入与在途输出失效，不转投新对话。接收回调入队后返回，停止等指令继续按优先级处理。Email/file 用于 Workflow 通知；微信虽然支持对话和通知能力，但必须先由用户发消息建立上下文，且每个上下文最多回复 10 条，因此不建议作为单向 Workflow 通知。Workflow 向双向插件发送通知同样不要求 Agent 绑定。

## Agent 对话指令

以下指令适用于启用 Agent 接收的双向渠道。`<...>` 为必填参数，`[...]` 为可选参数；输入时不用带括号。普通消息按顺序排队，回复回到该条消息的原地址。

| 输入 | 行为与使用条件 |
| --- | --- |
| `/new` | 创建并绑定新对话，成功后返回对话 ID；无需已有绑定 |
| `/resume` | 列出历史对话的名称、状态及完整恢复命令；不改变绑定，不等待当前回复完成 |
| `/resume <session_id>` | 选择已存在的 Agent 对话；目标不存在时明确报错，保留当前绑定 |
| `/stop` | 停止当前活动轮次并取消尚未开始的排队输入；独立处理，不等待模型完成。返回时轮次已停止；已有空闲对话也可使用，绑定不变 |
| `/append <补充内容>` | 运行中在下一安全边界加入补充内容，单独回复生效、失败或取消结果；空闲时以该内容开启新轮次并返回回答 |
| `/compact` | 整理当前对话上下文；运行中等待下一安全边界，空闲时启动一次整理。返回真实完成结果；无需压缩时不会伪造摘要 |
| `/fork [turn_id]` | 从当前对话的指定已完成轮次创建并绑定分支；省略 ID 时使用当前对话的最近轮次，该轮次必须已完成且有可用检查点 |
| `/workflow` | 列出最近的 Workflow 运行记录（最多 100 条），含名称、状态、运行 ID；可继续的记录附完整导入命令。不改变绑定，不等待当前回复完成 |
| `/workflow <session_id>` | 将该次 Workflow 运行的最终结果导入新 Agent 对话并绑定；支持 completed/partial 的最终结果，不启动 Workflow。这里的 ID 是 Workflow 运行 ID |

`/new`、带 ID 的 `/resume`、`/fork` 和带 ID 的 `/workflow` 是会话切换操作，会等待之前受理的普通消息完成。参数错误在停止或切换受理前拒绝：`/new`、`/stop`、`/compact` 不接受正文，ID 指令一次只接受一个 ID；正文含空格、多行时使用 `/append`。未知指令会返回支持的命令；未绑定时使用 `/new`，或先 `/resume` 再选择对话。

例如，发送 `/resume` 查看列表，再复制 `/resume agent_...` 选择对话，随后直接发送问题。运行中可用 `/append 请重点检查失败项` 补充要求，或用 `/stop` 停止。

Web 菜单中的 `/file`、`/settings`、`/clear` 是页面本地动作，外部渠道没有这些指令。Web 菜单 `/resume` 和 `/workflow` 使用既有选择面板；当前页面手动发送无参 `/resume` 尚未展示后端返回的历史列表，不能将它视为已完成的页面交互。

## Email 与文件

Email 的 SMTP 信息一般在邮箱设置的 **POP3/IMAP/SMTP/Exchange/CardDAV 服务** 中获取，主机一般为 `smtp.邮箱域名`，各邮箱的端口可能不同，以服务商说明为准。插件配置键保持 `host`、`port`、`password` 兼容，界面将 `password` 显示为“授权码”，输入后加密保存，不应填写邮箱登录密码。

| 参数 | 含义与 Gmail 示例 |
| --- | --- |
| `host` | SMTP 服务器：`smtp.gmail.com` |
| `port` | SMTP 端口：`587`（`starttls`）或 `465`（`implicit`） |
| `sender` | 邮件显示的发件人，通常与认证账号一致：`yourname@gmail.com` |
| `recipient` | 实际接收通知的单个邮箱，可与发件人相同，可由 Workflow 覆盖：`receiver@gmail.com` |
| `tls` | 连接加密方式：Gmail 的 587 使用 `starttls`，465 使用 `implicit` |
| `username` | SMTP 认证账号，一般为完整邮箱：`yourname@gmail.com` |
| `password`（授权码） | Gmail 开启两步验证后生成的 16 位“应用专用密码”，去掉显示空格；账号必须支持应用专用密码 |

仅收到 SMTP DATA 成功响应才记为成功；DATA 响应丢失记为投递不确定，不隐式重发。Gmail 的应用专用密码说明：https://support.google.com/accounts/answer/185833。

file 配置 `path`，可直接填写 `logs/notifications.log`；它相对系统 `data_dir` 解析，例如 `data_dir=/var/lib/workflowweave/data` 时写入 `/var/lib/workflowweave/data/logs/notifications.log`。父目录和文件自动创建，运行服务的用户需有写权限，以 UTF-8 追加日志。每条记录含 UTC 时间、channel/session/output ID、标题和正文，flush 后成功；写入、flush 和关闭失败显式报告。旧存量 `mock` 文件渠道在持久化读取时迁移为 `file`，保留资源 ID、路径和 Workflow 绑定。新建资源不再接受 `mock`。

## QQ、飞书与 Telegram

| 插件 | 账号配置 | 单向通知目标 |
| --- | --- | --- |
| qq | `app_id`、`client_secret` 凭据引用 | `target_kind` 为 `c2c/group/guild/dm`，`target_id` 为对应好友、群、频道或私信会话 ID |
| feishu | `app_id`、`app_secret` 凭据引用 | `target_kind` 为 `chat_id/open_id/user_id/email`，配套 `target_id` |
| telegram | `token` 凭据引用 | `chat_id` |

凭据引用例如 `{"kind":"env","name":"QQ_BOT_SECRET"}`；资源设置 `agent_enabled=true` 开启双向接收，回复使用入站消息的原路由。QQ 与飞书需在平台后台启用机器人对应事件和消息权限；Telegram 使用 long polling，同一 Bot 不应同时运行另一个 polling/webhook 接收端。消息发送仍受平台自身权限和会话限制。

**QQ 首次互动必须由用户完成**：先给机器人发送消息，或在群中 @机器人；插件无法自动代替用户完成。目标 ID 来自平台事件，不是普通 QQ 号码；仅填入 ID 无法建立互动，后续主动消息仍受平台权限和会话时效限制。

若连接时报 `QQ Bot 凭据无效（100016）`，请确认填写的是该机器人当前的 AppID 和 Client Secret。若曾在 QQ 开放平台重置过 Secret，需要在渠道资源中重新录入新值；不同资源即使使用相同 AppID，也可能保存了不同的 Secret。

飞书使用官方独立 [`lark-channel-sdk==1.4.0`](https://github.com/larksuite/channel-sdk-python)。该 SDK 负责 WebSocket 生命周期、事件标准化、传输去重和出站消息；适配器将文本消息回调交回应用事件循环，再由 `ChannelManager` 受理。为保留逐条消息身份和投递回执，关闭 SDK 的消息合并队列、自动重试和出站拆分；回复目标失效时明确失败，不降级为新消息。Agent 权限、绑定、SQLite 去重和重试策略仍由项目统一管理。如需使用其他飞书 OpenAPI 资源，再额外安装 `lark-oapi`。

## 微信：corespeed-io/wechatbot

微信渠道采用 [corespeed-io/wechatbot](https://github.com/corespeed-io/wechatbot) 的 `@wechatbot/wechatbot` Node SDK，网页内直接扫码登录并支持数字确认。SDK 将 Token 保存到配置的 `state_dir/credentials.json`（默认 `~/.wechatbot/credentials.json`，文件权限 0600），不经过 Web 或 Python IPC；首次登录成功后保存资源即可复用。

| 参数 | 说明 |
| --- | --- |
| `account_id` | 网页扫码成功后自动回填的 SDK 账号 ID |
| `state_dir` | 登录与消息上下文目录；例如 `/var/lib/workflowweave/wechat/main`，不同微信账号使用不同目录 |
| `command` | Node.js 可执行文件，例如 `node` 或 `/usr/bin/node`，要求 Node >=22 |
| `target_id` | 入站消息对端 ID，可用于 Workflow 通知目标；需先收到该用户消息建立上下文 |

**微信不建议作为单向通知渠道。** 微信只有在用户先发送消息、建立上下文后才能自动回复；微信 iLink 平台还限制每条用户消息对应的 `context_token` 最多回复 10 条消息，达到上限后需用户再次向 ClawBot 发消息获得新的上下文。它更适合用户发起后的双向对话或回复。
旧 OpenClaw 或 WeClawBot-API 配置不会自动迁移，请重新网页扫码登录。

后续自有实现将参考用户指定的 [腾讯云文章](https://cloud.tencent.com/developer/article/2651968)。该链接不表示腾讯对当前第三方项目的认证或保证；本轮请求得到防护页面，尚未核对文章正文。
