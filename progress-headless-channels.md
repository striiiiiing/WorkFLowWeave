# Headless Channels QA 进度

## 范围与验收依据

- 按用户要求覆盖真实前后端 `127.0.0.1:13000/14300`，测试浏览器固定为 Chromium 无头模式。
- 通知渠道行为依据：[通知插件设计](openspec/changes/add-notification-channel-plugins/design.md)；实例绑定依据：[双向渠道绑定设计](openspec/changes/bind-duplex-channel-conversations/design.md)；queue、`/stop` 和 test channel outbox 依据：[ChannelManager 设计](openspec/changes/redesign-agent-channel-manager/design.md)。
- proposal、design、task 均未修改。测试只创建唯一 ID 的 QA 资源，外部渠道配置保持禁用，不请求外部发送 API。

## 当前状态

| 步骤 | 状态 | 备注 |
| --- | --- | --- |
| 真实服务接入 | 完成 | 端口已有 QA 前后端服务；Playwright 配置显式复用现存服务。 |
| web/email/file schema 与 file CRUD | 通过 | 空配置验证、创建、编辑、删除及 API 回读均完成。 |
| 文件 Workflow 投递回读 | 通过 | 使用本机 OpenAI 兼容测试服务，真实 FileChannel 写入并读取临时文件。 |
| 外部渠道配置验证 | 通过 | QQ、飞书、Telegram、OpenClaw Weixin 缺字段配置拒绝、禁用占位配置接受；没有发送。 |
| test_channel duplex、queue、stop、binding、outbox | 通过 | 绑定和改绑分别路由成功；stop 取消正在运行的慢请求并中断排队项。 |
| 截图与浏览器日志 | 完成 | 每项结果、HTTP、console、pageerror 和最终截图均已落盘；console/pageerror 为空。 |
| 清理 | 完成 | QA channel、AI、source、workflow 资源无遗留；Agent session API 没有删除操作，会话保留在 QA 专用数据目录。 |
| 产品缺陷文档 | 无 | 失败项均来自测试装配/断言假设，修正后全部通过；未确认产品代码缺陷。 |

## 过程中的测试装配修正

- Element Plus 的 switch input 是隐藏控件；Playwright 改为点击其可见容器。
- AI provider 使用 `openai_compatible_api`；渠道 schema 校验失败的既定错误码是 `invalid_config`。
- 删除后读取不存在资源按当前错误映射返回 `409 not_found`，测试据此确认删除结果。
- `reuseExistingServer: true` 用于连接已经运行的指定 QA 服务。Agent 与 Workflow 模型请求只访问测试内的 loopback HTTP server；`api_key: null` 是受支持配置，因此不依赖 QA 服务的密钥。

## 环境观察

QA 服务的 `POST /api/credentials/protect` 返回 `500 credential_key_invalid`。这属于 QA 主密钥配置边界，不是本次渠道验收项；本次本地模型测试不需要凭据。测试过程没有使用真实外部平台凭据。

## 证据位置

- 最终汇总：[report-headless-channels.md](report-headless-channels.md)
- Playwright 规格：[channels-headless.spec.ts](frontend/tests/e2e/channels-headless.spec.ts)
- Playwright 服务配置：[playwright.channels.config.ts](frontend/playwright.channels.config.ts)
- 每个场景的 `result.json`、`http.json`、`console.json`、`pageerror.json`、`final.png`：`frontend/test-results/headless-channels-evidence/`
- 专项截图与文件投递回读附件：`frontend/test-results/headless-channels/`
