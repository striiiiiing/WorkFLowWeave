# 实施任务

依据 [proposal.md](proposal.md)、[design.md](design.md)、上游 commit 6914de4e4cae966b1a3f4c6531711c9dffd84fee 及 npm @wechatbot/wechatbot@2.2.0 元数据。2026-10-07 用户最新选择替代此前 WeClawBot-API；前端风险警示由用户明确要求删除，不以 Star 数量声称安全保证。

- [x] 1.1 先记录 SDK 选择、现有需求恢复、上游游标/重试差异与来源归属。
- [x] 2.1 小型 Node 依赖、SDK 登录/收发桥接及 Manager 确认后的游标持久化。
- [x] 2.2 网页扫码会话/API、前端专用登录组件，去除风险提示。
- [x] 2.3 配置说明、README 归属、Docker 依赖与文档。
- [x] 3.1 SDK/后端/前端定向测试、静态检查和构建。
- [x] 3.2 浏览器/联网 QR smoke、OpenSpec strict、差异审查与验证记录。

## 决策依据

- 选择 Node SDK：零 SDK 运行时依赖，npm 解包约 270 KiB，异步 onVerifyCode 可直接等待网页输入；现有 Node IPC 可复用。
- 不用 SDK MessagePoller：上游先保存 cursor 且 emit 不等待监听器，违反 Manager 受理后再推进游标的不变量；只复用 SDK 协议/存储，不手写平台 HTTP。
- SDK HttpClient 默认 maxRetries=2；显式设 0，避免同一通知在超时后重复发送。
- 微信登录与配置管理基础设施以既有 improve-channel-onboarding 设计为依据重新接入；过渡的无网页/无对话方案被用户最新指定 SDK 取代。

## 验证记录

验证记录：Node bridge/sdk 5 项通过；Python IPC/discovery 7 项通过；前端 `vue-tsc` 与生产构建通过，定向 Vitest 29 项通过；Ruff、Python compileall、OpenSpec strict、`git diff --check` 与 Docker Compose 配置检查通过。Compose 默认拉取 GHCR 镜像，源码构建仅通过 `compose.build.yaml` 显式启用；GitHub Actions 负责发布后端和前端镜像。联网扫码未自动完成，真实账号认证需用户在网页扫码；未向私人微信发送测试消息。
