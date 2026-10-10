# 非 email 渠道测试与复测结果

2026-10-09（Asia/Shanghai）。Email 未参与测试。用户授权真实平台测试，并明确默认单聊、利用用户首次消息事件提供的目标地址。

## 结论

自动回归全部通过；外部平台的真实收发不能全部计为通过。

| 渠道 | 真实测试与复测 | 结论 |
| --- | --- | --- |
| file | default_file、file_20b660e3-3ea4-4d0e-9461-5a6bd012a23b、inspection_file 成功追加并回读测试标记；浏览器 Workflow 也完成真实文件投递 | 真实投递通过 |
| QQ | `qq_AIBot` 通过真实 SDK 认证并进入 Gateway running；另一个实例仍由平台返回 `100016`。30 秒单聊观察未收到事件 | 一个实例连接通过，未完成真实回复闭环；另一个实例凭据/平台配置仍失败 |
| 飞书 | tenant token 认证成功；修复 WebSocket 代理后真实握手成功并保持 connected。30 秒单聊观察未收到事件 | 连接通过，未完成真实回复闭环 |
| Telegram | `getMe` 成功；将 Bot API/getUpdates 请求超时绑定到实例 30 秒后，真实 polling 初始化并进入 connected。30 秒单聊观察未收到事件；保存的主动目标仍 `chat not found` | 连接通过，未完成真实回复闭环；主动通知目标无效 |
| 微信 | 当前没有保存的微信资源/登录凭据；真实网页登录启动成功但 QR 请求失败，取消返回 204、取消后查询 404；显式 NODE_USE_ENV_PROXY=1 后，真实 SDK 及 Python 登录插件获得 QR，停止后进程回收，无 credentials.json 生成 | 代理诊断下 QR/取消通过，未扫码、未验证收发 |

QQ、飞书和 Telegram 单聊回复不要求手填通知目标：分别取 QQ c2c 的 `author.user_openid`、飞书 p2p 的 `chat_id`、Telegram 私聊的 `chat.id`，并使用事件中的 `message_id` 原路回复。主动通知目标和单聊回复分开记录。最终真实复测结果见 `conversation-final.json`：QQ `qq_AIBot`、飞书、Telegram 都已连接，但观察窗口没有首条入站消息，因此没有伪造回复成功；QQ 另一个实例明确返回平台错误 `100016`。

## 自动验证

| 检查 | 最终结果 |
| --- | --- |
| 后端渠道、生命周期、并行通知 | 136 passed，38.90 秒，零跳过，硬超时 60 秒 |
| 微信固定 Node SDK | 5 passed，零跳过 |
| 前端渠道绑定/API/Workflow 绑定及 QQ 参数校验 | 12 passed；同文件内 6 个 email 用例按选择器未运行 |
| Playwright | 7 passed，49.9 秒；五种渠道配置/校验/CRUD、桌面和移动截图、真实文件 Workflow、绑定/改绑/队列/停止/outbox |
| 类型检查、构建、ruff、定向 Prettier、diff check | 通过；构建有第三方 Zod 注释警告，后端有 SDK 弃用警告 |

补充的 Manager/Agent 测试明确覆盖 QQ c2c 和飞书 p2p 在无 target_id / target_kind 配置时，从首次入站取得原路回复地址，重复事件不重复执行或回复。这些用例替换网络 I/O，不是外部平台收发证据。

测试环境修正：移除 `frontend/tests/serve_agent_backend.py` 的空 `channel_factories` 注入，恢复项目默认 AI 工厂。Agent 仍使用已有 SmokeModel；Workflow 模型调用仅连接用例创建的本机 HTTP 服务。本轮生产代码只修改 QQ/飞书/Telegram 插件的 SDK 代理与超时适配；未修改资源配置、密钥或 proposal/design。真实文件日志保留了测试标记。

## 复现

仓库根目录：

```bash
rtk proxy timeout 60s .venv/bin/python -m pytest tests/channel tests/lifecycle/test_agent_channels.py tests/workflow/test_parallel_notification.py --ignore=tests/channel/test_email_channel.py -q
rtk proxy timeout 120s .venv/bin/python artifacts/channel-real-20261009/run.py --mode conversation --output artifacts/channel-real-20261009/conversation-retest.json
```

第二条命令真实启动 QQ、飞书和 Telegram 接收，只使用首条私聊事件地址回复，不保存配置或启用 Agent。默认观察窗口 30 秒；没有消息时返回 `awaiting_first_message`，而不是成功。失败和不确定结果不自动重发。当前保存资源的最终复测结果见 `conversation-final.json`；脚本也可在没有后端 API 时直接只读 `data/resources.json`。

前端目录：

```bash
rtk proxy npx playwright test --config playwright.non-email.config.ts --reporter=line
```

使用隔离测试后端与 13021 / 14321 端口，结束时回收。浏览器截图保存在 `frontend/test-results/non-email-channels/`。Tabbit 两次导航后页面被浏览器关闭，经诊断后结束任务，最终使用本机 Chromium 完成验证。

## 网络证据与待完成项

- QQ `qq-botpy==1.2.1` 的 Token、REST 和 Gateway 会话默认不读取代理；插件边界现在分别启用 `trust_env=True`，并保留 POST 不自动重试。`qq_AIBot` 已真实进入 running；另一个实例的 `100016` 是平台认证拒绝，需核对该实例的 QQ 开放平台配置。
- 飞书 `lark-oapi==1.7.3` 的 WebSocket `_ws_connect_kwargs()` 显式传 `proxy=None`；插件现在改为 `proxy=True`，真实握手已成功。依据 [websockets proxy 文档](https://websockets.readthedocs.io/en/stable/topics/proxies.html)，`proxy=None` 会禁用代理，默认/`True` 会启用环境代理发现。
- Telegram PTB 22.8 默认请求超时较短；插件现在将 Bot API 和 getUpdates 两套请求池绑定到实例 `timeout`（当前 30 秒），真实 polling 已连接。保存的主动通知目标仍被 Telegram 返回 `chat not found`；应使用首条私聊事件的 `chat.id`。
- 微信 Node 原生 fetch 需要当前部署显式启用环境代理；本轮仅在独立诊断进程设置 NODE_USE_ENV_PROXY=1，未改服务环境。真实登录及上下文建立仍需要本人扫码并向机器人发送消息。

认证与网络探测均不保存/输出 Token 或密钥；没有使用虚假发送回执。真实接收与登录进程均已结束，没有遗留后台监听或重复发送任务。
