# 双向渠道使用

> 本文描述上一版代码的使用方法。2026-09-24 的 [ChannelManager 重设计](../redesign-agent-channel-manager/design.md) 尚未迁移到代码，本文不代表新版队列及 HTTP 回执契约。

运行新版后端及前端。前端对话已走 `POST /api/channels/web/commands` 和 `GET /api/channels/web/sessions/{id}/events`；旧 `/api/agents` 对话接口仍投影到相同入口。

## QQ 官方机器人

本实现使用 QQ 开放平台 Bot，参考 QwenPaw 的官方 QQ 渠道，不是个人 QQ/OneBot。准备 app_id 和 Client Secret，并按平台控制台授权私聊、群聊或频道事件。

启动后端前设置环境变量 `QQ_BOT_CLIENT_SECRET`。通过渠道配置页面新建 `qq`，或者 `POST /api/channels` 保存以下资源（app_id 使用自己的值；密钥只写环境变量，不放进 JSON）：

```json
{
  "id": "qq_agent",
  "channel": "qq",
  "enabled": true,
  "agent_enabled": true,
  "options": {
    "app_id": "YOUR_APP_ID",
    "client_secret": {"kind": "env", "name": "QQ_BOT_CLIENT_SECRET"}
  }
}
```

`agent_enabled` 也可由配置页面的“接入 Agent 对话”开关控制。保存后接收配置自动同步；`GET /api/channels/status` 查询接收状态及错误。Agent 使用已有默认模型配置。QQ 首条消息自动建会话，支持 `/new`、`/resume <session_id>`、`/stop`、`/append 文本`、`/compact`、`/fork` 和 `/workflow`。群聊按群与发送者隔离上下文，回复仍发回原群；外部 `/resume` 仅接受该发送者在该对话内已有的会话。

若要供 Workflow 单向发送，在 options 增加 `target_kind`（c2c/group/guild/dm）和 `target_id`，并将渠道 ID 选为 Workflow 通知目标。`agent_enabled=false` 时仍可发送通知。目标应使用平台 OpenID/频道标识；QQ 主动消息权限、回复窗口和频率由平台决定，API 拒绝会产生失败回执，不伪装成功。

本轮未提供真实 QQ 凭据，因此验证使用本地 HTTP/WebSocket 协议模拟，尚未执行真实机器人联调。

## 本地测试渠道

先在渠道配置页面新建 `test` 并打开“接入 Agent 对话”，或执行：

```bash
curl -X POST http://127.0.0.1:4300/api/channels \
  -H 'Content-Type: application/json' \
  -d '{"id":"local_test","channel":"test","agent_enabled":true,"options":{"target":"local"}}'
```

注入一条消息；后端 Agent 仍使用真实配置的模型，测试渠道仅替代外部传输：

```bash
curl -X POST http://127.0.0.1:4300/api/channels/local_test/test/messages \
  -H 'Content-Type: application/json' \
  -d '{"request_id":"test-1","text":"你好","address":{"kind":"test","target":"room","sender":"alice","message_id":"test-1"}}'

curl http://127.0.0.1:4300/api/channels/local_test/test/messages
```

下一条消息使用新的 request_id/message_id，保持 target/sender 即继续当前会话。重复 request_id 不会再次执行或发送，改变其内容会报 request_conflict。`GET .../test/messages?after=1` 读取后续出站记录；`POST .../test/outcome` 传入相同消息信封查询持久的处理与投递回执。

会话绑定和请求回执保存在配置的 `data_dir` 下 `agents/channels.sqlite3`；测试出站列表在内存中，重启会清空。进程中断后未完成登记的请求明确报告结果未知，不自动重放工具操作或重新发送消息。已受理但尚未确认投递的请求会记录 `outcome_unknown / delivery_interrupted`。

## 定向自动化验证

```bash
timeout 60s uv run pytest -q tests/channel tests/lifecycle tests/interaction/test_agent_api.py
cd frontend
npm test -- tests/unit/agent-channel-api.test.ts tests/unit/agent-stream.test.ts tests/unit/agent_chat.test.ts tests/unit/agent-view.test.ts tests/unit/resource-config.test.ts
```
