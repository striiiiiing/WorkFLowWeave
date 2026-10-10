# 首条连接诊断与日志边界

## 依据与决策

- 用户反馈 Telegram 在等待首条私聊消息后显示“渠道连接失败”，飞书首条连接成功；QQ 曾在首条连接后失败，并在后续请求中收到平台 `100016`。
- 参考 `../../design.md` 和 `connect-channels-and-separate-builtin-plugins/design.md`：首条消息连接仍由唯一 `ChannelManager` 管理，确认消息必须使用首条事件的原地址发送，确认投递成功后才保存目标；本任务只补充可观测性和错误保真，不改变连接协议。
- 日志边界确定为：**框架记录连接生命周期，插件报告平台结果**。框架负责记录启动接收、进入等待、收到首条消息、开始发送确认、确认回执、保存目标、收尾和最终状态；QQ、飞书、Telegram 等插件不自行写应用日志，只将平台错误转换为 `ChannelDeliveryError` 或等价的结构化结果。
- 插件日志不得成为第二套诊断真源，也不得记录 Secret、Bot token、原始消息正文、完整凭据引用、完整地址或平台原始请求；框架日志只记录脱敏后的渠道 ID、资源 ID、阶段、状态、错误码、`delivery_uncertain`、异常类型和必要的固定分类。
- `config.json` 当前 `log_file` 为 `null`。因此当前实例没有由 `JsonLogSink` 管理的持久化应用日志文件；标准输出是否保留取决于启动器，不能把“没有日志文件”解释为“没有发生错误”。启用文件日志后，统一由框架的 `workflowweave` logger 和脱敏 formatter 写入。
- Telegram 的 `BadRequest`、限流和网络错误必须保留为 `telegram_rejected`、`telegram_rate_limited`、`telegram_send_uncertain` 等领域错误；可以记录固定的安全分类，但不直接转储 Telegram 异常正文。QQ 的 `100016` 继续表示平台拒绝当前 AppID/Secret 配对，不能由框架改写凭据或伪造连接成功。
- 若确认投递返回失败，连接状态必须保留该领域错误；若保存首条目标或临时接收清理失败，必须报告对应的持久化或清理错误，不能把已有领域错误覆盖成无上下文的“渠道连接失败”。
- 本次 QQ `qq_AIbot` 实测失败发生在首条消息之后，后端状态为 `channel_connection_failed`、`exception_type=ValidationError`，而不是 token 认证阶段。根因是框架将平台原始消息 ID 直接作为 `Notification.output_id`；QQ/Telegram 的消息 ID 允许 `:` 等字符，不满足内部 `ID` 格式。修复为框架生成 `connection-` 加 SHA-256 的内部输出 ID，原始 ID 仍只保留在回复地址中。

## 工作项

- [x] 在 `ChannelConnections` 增加脱敏结构化阶段日志：接收首条消息、开始发送“成功连接”、投递结果、保存目标结果、临时接收收尾和最终状态；日志字段不得包含消息正文、token 或 Secret。
- [x] 检查并修正首条连接异常边界：保留 `DeliveryResult.error`，区分确认被平台拒绝、发送结果不确定、目标保存失败、接收器失败和清理失败；`ValidationError` 转换为结构化连接错误，普通未知异常只保留固定消息与异常类型。
- [x] 修正平台消息 ID 与内部通知 ID 的边界；回归测试覆盖含 `:` 和 `/` 的远端消息 ID，确认首条连接不会因内部 ID 校验失败而泛化报错。
- [x] 为 Telegram 平台错误增加安全、可测试的分类信息；其投递错误不会被框架改写成成功，首条消息与 Telegram 相同的内部 ID 边界由共享连接测试覆盖。
- [x] 为 QQ `100016` 保留平台码和中文诊断；真实核验只输出资源 ID、平台码和认证布尔值，不输出 Secret 或 token。
- [x] 增加回归测试：首条确认失败不保存目标且保留领域错误；发送不确定不自动重发；保存失败和清理失败可区分；阶段日志存在且不泄露敏感字段。
- [x] 在配置启用 `log_file` 的测试生命周期中验证日志文件实际生成并可检索；`log_file: null` 的实例只报告“未配置持久化日志”，不凭空生成默认日志路径。
- [x] QQ `qq_AIbot` 已在修复后的运行进程中重新完成首条私聊连接：状态为 `connected`、确认投递成功、目标已保存为首条 c2c 事件的 `target_id`；没有输出消息正文或凭据。
- [ ] Telegram 仍需在修复后的运行进程中重新进行首条私聊真实测试，记录“等待首条消息”“平台拒绝”“发送结果不确定”“确认成功”状态；未收到首条消息或没有日志证据时，不宣称收发闭环成功。飞书已成功的结果继续保留为对照证据。

## 验收与验证

- 后端相关测试每次使用 60 秒硬超时，随后运行 Ruff、`git diff --check`，再运行受影响的前端类型检查/构建和最小 smoke。
- 日志验收只检查结构和脱敏：允许渠道名、资源 ID、阶段、错误码、异常类型及固定分类；禁止 Secret、token、原始正文和完整平台地址。
- 真实平台复测必须使用现有凭据解析和真实 SDK/HTTP/WebSocket 或 long polling 路径，不添加 mock 成功分支、不自动重试不确定投递，也不覆盖用户保存的凭据。

## 当前证据

- `artifacts/channel-real-20261009/telegram-timeout-retest.json` 只证明 Telegram polling 初始化并进入等待首条消息，不能证明首条回复成功。
- `artifacts/channel-real-20261009/telegram-retry.json` 记录过主动发送的 `telegram_rejected` / `BadRequest`，但没有本次首条消息操作的阶段日志。
- 飞书真实连接已成功；QQ 一个资源可取得 token，另一个同 AppID 资源返回平台 `100016`，说明该失败不能仅归因于通用网络代理。
- 当前运行资源 `qq_AIbot` 的首条消息失败已定位为 `ValidationError`，不是 token 拒绝；修复后真实重测已返回 `connected`，确认消息投递和目标保存均成功。Telegram 的修复后真实首条消息仍待复测。
