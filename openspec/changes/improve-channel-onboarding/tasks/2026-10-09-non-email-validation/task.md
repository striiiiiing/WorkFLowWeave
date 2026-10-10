# 非 email 渠道测试

## 范围与依据

- 用户要求测试除 email 外的全部渠道，随后明确同意真实平台测试。
- 依据 `plugins/channel/README.md`，覆盖 file、qq、feishu、telegram、wechat_openclaw，以及共享 Web/Agent 路由。
- 依据 `add-notification-channel-plugins/design.md`、`improve-channel-onboarding/design.md`、`adopt-corespeed-wechatbot/design.md` 验证插件、SDK、投递回执、网页登录与消息路由契约；不修改 proposal/design。
- 本轮为验证任务。真实发送复用现有 ChannelManager、凭据解析和保存的实例配置；没有自动重试。Telegram 首次初始化失败、发送尚未开始后，按用户要求显式重试一次，平台明确拒绝；没有重复发送不确定消息。超时采用实例已保存的 timeout（当前 30 秒），后端单测命令硬超时 60 秒，均依据既有配置/设计。
- 用户补充：默认单聊，首次事件提供飞书 chat_id / QQ user_openid。单聊测试使用该事件的不可变 address / message_id 原路回复，不要求预填通知目标；主动 Workflow 通知和单聊回复分别记录。原路回复机制已存在，只扩展验证用例，不修改设计或增加第二份目标存储。
- 真实接收测试仅在测试进程内启用接收，未保存 agent_enabled 或 Agent 绑定；30 秒首条消息观察窗口用于本轮 smoke，不是业务默认值。没有入站事件或连接失败不能宣称回复通过。微信无凭据时需用户扫码，认证通过、模拟平台测试通过与真实投递通过分别记录。
- Telegram 失败调查：仓库允许的 `python-telegram-bot>=22.8,<23` 在 PTB 22.8 中，HTTPXRequest 默认连接/读取/写入/连接池超时为 5/5/5/1 秒；`Application.initialize()` 和 polling bootstrap 会同步进行 Bot API 请求。项目已有 `ChannelConfig.timeout`（`src/workflowwe/models.py`，当前实例 30 秒），且 `ChannelManager` 用该值作为同一启动操作预算，因此两套 PTB request pool 均使用实例 timeout，避免 SDK 的 5 秒默认值另立一套配置；没有增加自动重试。修复后 Telegram 已完成真实 polling 初始化并进入 connected，观察窗口没有首条私聊事件。
- QQ 代理修复依据：已安装 `qq-botpy==1.2.1` 的 `Token.update_access_token`、`BotHttp.check_session` 和 `BotWebSocket.ws_connect` 都自行创建未启用环境代理的 aiohttp session。插件边界现在让 Token、REST、Gateway 分别使用环境代理；Gateway 还把 websockets 的环境代理选择结果传给 aiohttp，避免 aiohttp 只查 `WSS_PROXY`。POST 失败后的原有不自动重试语义保持不变。真实 `qq_AIBot` 复测已进入 running，另一实例返回平台 `100016`。

## 进度

- [x] 非 email 后端渠道、生命周期、并行通知回归：最终 136 passed，38.90 秒，零跳过，60 秒硬超时内完成。
- [x] 补充 QQ c2c、飞书 p2p 首次消息无预填 target 的 Manager/Agent 原路回复与去重断言。
- [x] 微信固定 Node SDK 契约：5 passed，零跳过。
- [x] 当前配置真实文件落盘：三个实例成功，均回读测试标记。
- [x] QQ、飞书、Telegram 真实认证、通知和首条单聊监听复测；未完成的真实闭环明确记录。
- [x] 微信真实二维码请求、取消和进程回收；显式 Node 环境代理诊断成功，无扫码、无 Token 生成。
- [x] 前端定向单测 12 passed；另外 6 个 email 用例按选择器排除。类型检查、构建、ruff、定向 Prettier、diff check 通过。
- [x] 浏览器 7 passed：五渠道配置/校验/CRUD、桌面与移动截图、真实 Workflow 文件投递、绑定/改绑/停止/outbox。
- [x] Telegram 的 Bot API 与 getUpdates 两套请求池均复用实例 `timeout`；契约测试验证所有 PTB 超时参数。修复后真实 polling 已连接；观察窗口没有首条私聊事件，所以没有宣称回复闭环通过。
- [x] 修复 QQ Token、REST、Gateway 的环境代理适配；新增 Token 刷新/平台拒绝契约测试，QQ 适配器相关测试通过。
- [x] 修复飞书 WebSocket 环境代理适配；真实握手复测连接成功。
- [x] 三个平台最终真实单聊复测：QQ `qq_AIBot`、飞书、Telegram 已连接；观察窗口内没有首条私聊事件，因此没有发送或伪造回复。QQ 另一个实例在认证阶段明确返回 `100016`。
- [x] 删除浏览器测试后端的空 AI 工厂注入，恢复既有默认工厂；Agent 仍使用既有 SmokeModel，Workflow 只访问用例启动的本机模型服务。
- [x] 修复飞书 WebSocket 代理适配：锁定的 `lark-oapi==1.7.3` 在 `lark_oapi/ws/client.py::_ws_connect_kwargs()` 对支持 `proxy` 参数的 websockets 显式传 `None`；当前安装的 websockets 15.0.1 将其解释为禁用环境代理。仅在插件 SDK 边界把这个 opt-out 改为 `proxy=True`，沿用 websockets 的环境代理发现，不改核心路由或网络配置；SDK 生命周期测试断言最终传入代理参数，飞书插件测试 9 passed。
- [x] 独立端口 13021 / 14321 完成 smoke；原先 13000 端口占用，使用专用端口避免影响现有服务。
- [x] 记录各渠道结论与阻塞项，审查新增文件；真实测试进程和扫码进程已回收。
- [ ] 外部平台真实单聊收发全部通过：连接已恢复，但本轮没有收到首条私聊事件；QQ 一个实例仍有平台 `100016`，微信仍未扫码。

## 证据

- `artifacts/channel-real-20261009/README.md`：汇总、复测结论与可复现命令。
- `artifacts/channel-real-20261009/run.py`：可复现真实测试脚本；不创建 email 实例或发送邮件，不输出秘密。
- `artifacts/channel-real-20261009/result.json`：首次真实通知测试；三个文件实例成功。
- `artifacts/channel-real-20261009/telegram-retry.json`、`telegram-target.json`：发送被平台明确拒绝，getChat 确认 chat not found。
- `artifacts/channel-real-20261009/auth-diagnostics.json`：显式 HTTPX/环境代理身份探测，与 SDK 运行结果分开。
- `artifacts/channel-real-20261009/conversation-retest.json`、`feishu-conversation-retry.json`：首次单聊事件监听复测，飞书明确 TimeoutError。
- `artifacts/channel-real-20261009/conversation-final.json`、`qq-final-retest.json`：代理/超时修复后的最终真实复测；connected 表示平台连接已建立，`awaiting_first_message` 表示观察窗口内没有可用于原路回复的入站事件。
- `artifacts/channel-real-20261009/feishu-websocket-diagnostic.json`：官方 SDK 能取得 WebSocket 地址，但不是连接成功。
- 本次飞书代理修复的运行依据：锁定 SDK 源码 `lark_oapi/ws/client.py::_ws_connect_kwargs()` 和当前 websockets 15.0.1 `connect()` 签名；官方代理说明见 [websockets proxies](https://websockets.readthedocs.io/en/stable/topics/proxies.html)。由于当前 backend API `127.0.0.1:4300` 未启动，最终真实复测脚本改为只读 `data/resources.json` 加载保存资源；飞书 tenant token 和 WebSocket 握手均成功，SDK 连接契约与插件回归也已通过。
- `artifacts/channel-real-20261009/wechat-login.json`、`wechat-proxy-login.json`：实际网页登录失败后，显式开启 Node 代理的真实插件 QR/取消诊断通过；未登录。
- `frontend/test-results/non-email-channels/`：最终通过的浏览器证据与十张桌面/移动截图。
