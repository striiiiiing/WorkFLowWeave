# 双向渠道后端使用说明

本版本由一个 `ChannelManager` 管理 Web、QQ 和 test 的入站队列与 Agent 消费。`frontend/` 不需要改动；现有 Web 请求和 SSE 继续使用原字段、状态码及事件游标。

## Web

前端写请求进入 `POST /api/channels/web/commands`，事件从 `GET /api/channels/web/sessions/{session_id}/events` 读取。后端会等待请求取得真实 Agent 结果后返回；排队期间不会返回缺少 `turn_id` 的成功响应。旧 `/api/agents` 写接口也投影到同一 WebChannel 和 session 队列。

## QQ

QQ 渠道使用官方 Bot Gateway 与 REST。配置至少包含 `app_id` 和凭据引用：

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

Gateway 消息先进入 Manager，再由 Agent 端口处理；同一 `request_id` 不会重复执行。Agent 回复固定发送到原 QQ 消息地址。`target_kind` 与 `target_id` 是 Workflow 单向 `send` 的独立目标，关闭 `agent_enabled` 不会关闭单向发送。真实 QQ 平台联调需要用户提供凭据和平台授权，本仓库只用模拟 Gateway/REST 做协议和闭环测试。

## test 渠道

test 渠道用于后端自动化和本地诊断。注入接口为：

```bash
curl -X POST http://127.0.0.1:4300/api/channels/local_test/test/messages \
  -H 'Content-Type: application/json' \
  -d '{"request_id":"test-1","text":"你好","address":{"kind":"test","target":"room","sender":"alice","message_id":"test-1"}}'
```

出站记录通过 `GET /api/channels/local_test/test/messages` 查看，处理和投递回执通过 `POST /api/channels/local_test/test/outcome` 查询。相同请求返回原回执，改动内容会返回 `request_conflict`。outbox 是内存调试记录；绑定和回执存放在 `data_dir/agents/channels.sqlite3`。

## 恢复和限制

重启时，Manager 只根据 Agent 事件日志恢复有明确证据的会话或轮次；没有证据的请求保持 `outcome_unknown`，不会自动重放模型、工具或平台发送。已完成 Agent 操作但未确认渠道投递的请求显示 `delivery_interrupted`。当前没有真实 QQ 凭据，因此未执行线上机器人联调。
