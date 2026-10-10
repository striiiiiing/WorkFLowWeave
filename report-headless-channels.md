# Headless Channels QA 报告

## 结果

2026-10-06 使用 Chromium 无头模式完成全部 3 个 Playwright 场景，3/3 通过。测试连接到运行中的前端 `127.0.0.1:13000` 和真实后端 `127.0.0.1:14300`；未启动 headed 浏览器，也未向外部通知平台发送消息。

运行命令（工作目录 `frontend/`）：

```bash
rtk proxy npx playwright test --config playwright.channels.config.ts --reporter=line
```

## 验收项

| 验收项 | 状态 | 结果 |
| --- | --- | --- |
| web schema | 通过 | `/api/plugins` 返回 object schema，`properties` 为空且拒绝额外字段。 |
| email schema 与表单 | 通过 | 核对 SMTP 必填字段、TLS 枚举及 recipient 的 Workflow 标记；空表单不发保存请求；禁用的占位配置保存成功。 |
| file schema 与无效配置 | 通过 | 核对必填 `path`、非空约束及路径标记；UI 空路径阻止保存，API 空路径返回 `422 invalid_config`。 |
| file channel CRUD | 通过 | UI 创建、编辑、删除；创建/编辑后 API 回读路径，删除返回 204；删除后回读为 `409 not_found`。 |
| Workflow 文件真实投递与回读 | 通过 | Workflow 运行完成，实际 FileChannel 写入临时文件；回读含成功标记和渠道 ID。模型请求只访问本机 OpenAI 兼容测试服务。 |
| 外部平台配置验证 | 通过 | QQ、飞书、Telegram、OpenClaw Weixin 缺字段配置均返回 `422 invalid_config`；禁用的占位配置均返回 201；未调用发送接口。 |
| test_channel binding / duplex | 通过 | 从未绑定状态绑定第一会话并验证回复，再改绑第二会话并验证消息路由到新会话。 |
| test_channel queue / stop / outbox | 通过 | 慢请求运行时注入排队项，再发送高优先级 `/stop`；活动轮次取消、排队项未投递，outbox 含两条完成回复及停止回执。 |
| console / pageerror | 通过 | 三个场景的浏览器 console 和 pageerror 记录均为空。 |
| 截图 / HTTP | 通过 | 每个场景均保留最终截图、HTTP、console、pageerror 和结果状态；关键页面另有截图附件。 |

负向状态码是测试预期的一部分：空配置返回 422；删除资源后再次读取返回 `409`，错误码为 `not_found`。其 HTTP 映射与现有 `interaction/errors.py` 契约一致。

## 证据

每个场景均保存 `result.json`、`http.json`、`console.json`、`pageerror.json` 与 `final.png`：

- Schema、无效配置与 CRUD：[状态](frontend/test-results/headless-channels-evidence/web-email-file-schemas-invalid-settings-and-file-channel-crud/result.json)、[HTTP](frontend/test-results/headless-channels-evidence/web-email-file-schemas-invalid-settings-and-file-channel-crud/http.json)、[console](frontend/test-results/headless-channels-evidence/web-email-file-schemas-invalid-settings-and-file-channel-crud/console.json)、[pageerror](frontend/test-results/headless-channels-evidence/web-email-file-schemas-invalid-settings-and-file-channel-crud/pageerror.json)、[截图](frontend/test-results/headless-channels-evidence/web-email-file-schemas-invalid-settings-and-file-channel-crud/final.png)
- Workflow 文件投递：[状态](frontend/test-results/headless-channels-evidence/file-channel-delivers-a-real-workflow-notification-to-a-readable-temp-file/result.json)、[HTTP](frontend/test-results/headless-channels-evidence/file-channel-delivers-a-real-workflow-notification-to-a-readable-temp-file/http.json)、[console](frontend/test-results/headless-channels-evidence/file-channel-delivers-a-real-workflow-notification-to-a-readable-temp-file/console.json)、[pageerror](frontend/test-results/headless-channels-evidence/file-channel-delivers-a-real-workflow-notification-to-a-readable-temp-file/pageerror.json)、[截图](frontend/test-results/headless-channels-evidence/file-channel-delivers-a-real-workflow-notification-to-a-readable-temp-file/final.png)、[文件回读](frontend/test-results/headless-channels/channels-headless-file-cha-dd7b1-ion-to-a-readable-temp-file-chromium-headless/file-delivery-readback.log)
- test_channel duplex、queue、stop 与 outbox：[状态](frontend/test-results/headless-channels-evidence/test-channel-routes-duplex-input-through-binding-queue-stop-and-outbox/result.json)、[HTTP](frontend/test-results/headless-channels-evidence/test-channel-routes-duplex-input-through-binding-queue-stop-and-outbox/http.json)、[console](frontend/test-results/headless-channels-evidence/test-channel-routes-duplex-input-through-binding-queue-stop-and-outbox/console.json)、[pageerror](frontend/test-results/headless-channels-evidence/test-channel-routes-duplex-input-through-binding-queue-stop-and-outbox/pageerror.json)、[截图](frontend/test-results/headless-channels-evidence/test-channel-routes-duplex-input-through-binding-queue-stop-and-outbox/final.png)

专项交互截图也保存在 [Playwright 输出目录](frontend/test-results/headless-channels/)。

## 环境边界

- 模型请求由测试内的 loopback HTTP 服务响应；外部平台配置使用禁用的占位资源，没有实际凭据或发送请求。
- QA 后端的 `POST /api/credentials/protect` 探测返回 `500 credential_key_invalid`。本次渠道流程通过支持的 `api_key: null` 调用本机模型服务，因此没有覆盖主密钥配置。
- 创建的渠道、AI、source 和 workflow 资源已清理；后端没有 Agent session 删除接口，测试会话留在专用 QA 数据目录中。
- 未发现产品代码问题，因此没有新增 `docs/qa-headless-channels-*.md`。
