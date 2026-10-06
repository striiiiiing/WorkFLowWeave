# 设计：通知适配器作为插件

状态：**2026-10-04 用户确认：插件目录改为 plugins/channel/；file 用 logging 日志方案；删除全部原先预配置的 Collector。**

## 1. 边界与前置设计

本变更依赖既有 `redesign-agent-channel-manager` 对 Manager、统一队列和双向 Agent 端口的设计。这里不重写那份设计，只规定具体适配器必须如何归属和接入。

核心层（`src/workflowweave/channel/`）只拥有：

- `ChannelType`、`NotificationChannel`、双向会话输入和投递回执等通用协议；
- 唯一 `ChannelManager`、队列、生命周期、超时和去重；
- 平台无关的 `Notification`、入站信封、`DeliveryResult` 和能力注册视图。

核心层不导入 `botpy`、`lark_oapi`、`telegram`、OpenClaw 或文件通道实现，也不保留 QQ/飞书/Telegram 的地址枚举。平台地址由插件验证后作为不透明的 `reply_route` 交给 Manager。

每个具体适配器都放在独立目录：

```text
plugins/channel/
├── email/
├── file/
├── qq/
├── wechat_openclaw/
├── feishu/
└── telegram/
```

每个目录至少包含 `plugin.json`、`main.py` 和实现模块。`main.py` 只通过 `ChannelPluginApi.register_channel(...)` 注册一个 channel type；插件不修改核心注册表，不创建第二个 Manager，也不保存另一份 Agent 会话状态。

## 2. 能力矩阵

| 插件目录 | 稳定能力名 | 单向通知 | 双向 Agent 对话 | 推荐官方实现 |
| --- | --- | ---: | ---: | --- |
| `plugins/channel/email` | `email` | 是 | 否 | `aiosmtplib` SMTP |
| `plugins/channel/file` | `file` | 是 | 否 | Python 标准库 logging.FileHandler |
| `plugins/channel/qq` | `qq` | 是 | 是 | 腾讯 `qq-botpy` |
| `plugins/channel/wechat_openclaw` | `wechat_openclaw`（暂定） | 是 | 是 | OpenClaw Weixin/Tencent iLink bridge |
| `plugins/channel/feishu` | `feishu` | 是 | 是 | 飞书 `lark-oapi` |
| `plugins/channel/telegram` | `telegram` | 是 | 是 | `python-telegram-bot` |

`capabilities` 仍由插件声明为 `notification` 或 `notification, conversation`。`agent_enabled` 只对声明 `conversation` 的实例有意义；Email 和文件实例始终不能启动入站接收。

## 3. 注册、依赖与配置

### 3.1 清单和依赖

所有插件遵循当前 WorkFLowWeave v1 清单格式：

```json
{
  "id": "telegram",
  "version": "1.0.0",
  "kind": "channel",
  "api_version": 1,
  "entry": {"backend": "main.py"}
}
```

平台 SDK 是插件依赖，不进入核心包的必需 import 路径。发布时用可选依赖组或插件发行包提供它们；实现阶段先验证当前 SDK 的 Python 版本和异步 API，再锁定兼容范围。插件导入缺失依赖时沿用现有 discovery 诊断，不能让其他插件全部消失，也不能悄悄降级到手写协议。

插件收到的凭据通过既有 `CredentialResolver` 解析。`options` 只保存非秘密配置或凭据引用，不能保存明文 token、密码、app secret。

### 3.2 公共生命周期

每个实例遵循既有 `create(config, credentials)` 工厂和 Manager 生命周期：

1. `create` 只校验配置并构造适配器，不建立网络连接或启动接收循环。
2. `start` 准备单向发送所需客户端；它成功不代表双向接收已经连接。
3. Manager 按 `agent_enabled` 和能力声明调用 `start_receiving(enqueue)`；SDK 回调只做平台事件校验、归一化和 `await enqueue(inbound)`。
4. `send` 只执行单向通知，不进入 Agent 队列、不创建会话、不隐式启动接收。
5. `stop_receiving` 和 `stop` 等待自有任务结束，报告清理错误；不得在后台留下 Manager 不知道的模型任务。

双向插件产生的每条输入必须包含固定 `channel_id`、平台 `conversation_key`、发送者、平台消息 ID 和不可伪造的 `reply_route`。消息 ID 交给 Manager 去重，插件不另建业务去重表。

## 4. Email 方案（已确认）

### 4.1 范围

Email 只做 SMTP 出站，不轮询邮箱，不解析回复，不声明 `conversation`。Workflow 可以用本次调用选项覆盖收件人；覆盖项通过同一 schema 验证。

### 4.2 配置

拟保留并规范化现有配置：

| 字段 | 语义 | 暂定值或要求 |
| --- | --- | --- |
| `host` | SMTP 主机 | 必填 |
| `port` | SMTP 端口 | 必填；常见 587/465 由用户显式设置 |
| `sender` | 发件人 | 必填 |
| `recipient` | 默认收件人 | 必填，可被 Workflow 调用覆盖 |
| `tls` | `none`、`starttls`、`implicit` | 默认 `starttls`，避免明文 SMTP |
| `username` | SMTP 用户名 | 可选；设置时必须有 `password` |
| `password` | 凭据引用 | 通过 `CredentialResolver` 解析 |

`ChannelConfig.timeout` 作为一次发送的总预算，默认沿用现有 30 秒。凭据缺失、TLS 不匹配、认证拒绝、RCPT 拒绝和 DATA 明确拒绝都返回失败；服务器已接受 DATA 但连接随后丢失时返回 `uncertain` 语义，不自动重发，避免重复邮件。

### 4.3 SDK 选择依据

仓库已经直接依赖并使用 `aiosmtplib`，它提供异步 SMTP、STARTTLS、隐式 TLS 和认证。继续使用它比再引入同步 SMTP 或自行写协议更小；不增加 IMAP/POP 依赖，因为用户要求的 Email 只被定义为单向通知。

## 5. 本地文件日志方案（已确认）

使用 Python 标准库 `logging.FileHandler` 以 UTF-8 追加可读日志，正式能力名为 `file`。每条通知记录 UTC 时间、channel/session/output 标识、标题和正文；不再采用提案初稿的 JSONL、fsync 参数或手写文件 Handler。

- path 必填，相对 data_dir 解析；创建父目录，以追加模式保留原有内容。
- 同一规范化路径共享 Handler，使用其锁串行化记录，按引用计数管理关闭。
- emit 内部 flush；覆写 handleError 使写入/flush 异常向调用方抛出，不能只写 stderr 后返回成功。
- I/O 放在线程中；取消不能终止已开始的线程，必须保留投递不确定语义，关闭时等待在途写入。
- 不自动轮转、不自动重试，不监听文件入站，只声明 notification。
- 已有 channel: mock 文件资源通过边界迁移改为 file，保留 ID、path 和 Workflow 覆盖；不保留 mock 别名或重复实现。

## 6. 双向平台方案

### 6.1 QQ

使用腾讯维护的 `qq-botpy`（模块 `botpy`），由 SDK 负责 Gateway、鉴权、事件模型和发送 API。插件只实现：

- 配置 `app_id`、secret 凭据和单向通知目标；
- 用 SDK 事件回调生成统一入站信封；
- 通过 SDK 的好友/群/频道发送方法完成通知或原路回复；
- 按 SDK 的 Gateway 重连、心跳、事件去重契约报告接收状态。

不再在 WorkFLowWeave 内重复实现 QQ token、WebSocket payload 和 REST 路由。SDK 没有覆盖的回执不被伪造为成功。

### 6.2 微信“小龙虾”

当前将名称解释为 OpenClaw Weixin 通道。其维护的外部插件通过二维码登录和 Tencent iLink API 工作，Python WorkFLowWeave 不应复制协议。拟采用受支持的 OpenClaw sidecar/bridge：

- sidecar 负责 QR 登录、账号会话、iLink 长连接和平台协议；
- WorkFLowWeave 插件通过稳定的进程/IPC 边界交换 JSON 入站事件和发送请求；
- 入站消息仍由 WorkFLowWeave Manager 排队，出站回复使用 sidecar 返回的原始路由；
- sidecar 未安装、登录过期或响应不确定时返回明确错误，不静默切换成另一套微信协议。

由于 `@tencent-weixin/openclaw-weixin` 与 `openclaw-weixin` 的包名和版本存在漂移，sidecar 的准确启动命令、版本和 IPC 形式在用户确认后再冻结。若“小龙虾”不是 OpenClaw，应先替换本节方案。

### 6.3 飞书

使用 `lark-oapi` 的异步 API 和 WebSocket 事件模式。默认不新增公网 Webhook：SDK 负责 app token、事件签名/解码、WebSocket 连接和类型化 API；插件把文本消息归一化后入队，并用消息 reply API 发回原会话。配置包含 app id、secret 凭据、单向目标和允许的事件类型；凭据均走 resolver。

### 6.4 Telegram

使用 `python-telegram-bot` 的 `Application` 和异步 long polling。`start_receiving` 启动一个由 Manager 管理的 Application；消息 handler 只校验 chat/user 身份、构造入站信封并入队。单向通知和原路回复使用 SDK 的 `send_message`，保留 chat ID 和 reply-to message ID。默认不使用公网 webhook，避免额外暴露入口；用户若需要 webhook，应另建配置与部署需求。

## 7. 删除全部原先预配置的 Collector

删除默认注册的 MockCollector、LogsCollector、HistoryCollector、它们的具体实现与配送的 plugins/mock。核心保留自定义插件所需 Collector 协议、注册接口与注册视图；不默认创建 Collector、Setter 或通知资源。

新资源集合为空，删除旧 default_file/mock 种子。用户已保存的来源与数据不批量删除，旧 Collector 来源沿用 MCP/CLI 迁移错误，不静默变为空配置；旧文件渠道按第 5 节迁移。

唯一注册器增加 plugins/channel/<plugin> 分组扫描，分组目录本身不当作插件；兼容根目录自定义插件，跨层重复 ID 使用同一冲突检查。

## 8. 验证策略

实现后按以下顺序验证：

1. 插件清单、能力声明、schema 和缺失依赖诊断。
2. Email 的 TLS、凭据、DATA 成功/拒绝/不确定，以及无入站能力。
3. 文件日志的路径解析、并发追加、flush、写入错误和重启后可读性。
4. QQ、微信 bridge、飞书和 Telegram 的 SDK mock/contract 测试；每条入站必须真实进入 Manager 队列。
5. Manager 与 Agent 的双向闭环、原路回复、重复消息和独立单向发送。
6. 新资源无采集器/旧文件种子，旧资源迁移可重复。
7. 目标单测、类型/静态检查、受影响包构建、最小 smoke test；后端单测单次硬超时 60 秒。
