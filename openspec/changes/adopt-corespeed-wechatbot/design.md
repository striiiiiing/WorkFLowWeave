# 设计：轻量 WeChatBot SDK 接入

## Approach

以用户最新指定项目为准，保留 wechat_openclaw 资源能力名，notification/conversation 能力和网页扫码。依赖固定 @wechatbot/wechatbot=2.2.0 + qrcode=1.5.4，Node >=22；不安装 openclaw 或独立第三方 HTTP 服务。

SDK 顶层尚未导出细粒度协议/解析/认证服务，桥接通过固定包入口定位 dist 下模块，版本升级必须通过真实 SDK 契约测试。核心不导入具体 SDK，仍仅负责通用登录会话和平台消息路由。

## Invariants

1. Token 只由 SDK FileStorage 保存于 state_dir/credentials.json，模式 0600；不经过 Python/Web IPC，也不存 resources.json。不同微信账号使用独立 state_dir，缺少凭据或账号不匹配明确报错，后台不自动发起扫码。
2. SDK Authenticator 登录回调直接映射 JSON 状态；二维码 PNG 由 qrcode 标准库生成。数字经 stdin，仅在等待确认时提交；刷新、取消、配置目录/命令变更或页面卸载终止旧进程，旧响应不能回填新配置。
3. 登录预算 300 秒，第一次 QR 请求预算 30 秒，结束进程预算 5 秒，网页查询间隔 1 秒；依据既有 improve-channel-onboarding 设计，保留已验证的体验预算。SDK 的轮询间隔 2 秒及最多刷新 3 次由 SDK 处理，不复制平台认证逻辑。
4. SDK HttpClient 显式禁用重试。登录和通知均用其真实 ILinkApi；通知成功需要有效平台成功回执，缺上下文/平台拒绝明确失败，断链/超时/部分分片结果不确定，不隐式重发。
5. 接收由 SDK getUpdates/MessageParser/ContextStore 转换；桥接逐条等待 Manager inbound_ack，然后 await SDK FileStorage 保存 cursor。拒绝入队、取消或未确认不推进游标；存储异常显式失败。仅文本/语音识别文字进入 Agent，不把媒体占位符伪装成文本。
6. SDK 使用 Node 原生 fetch，服务器已有显式 NODE_USE_ENV_PROXY=1 时由 Node 自身使用环境代理，取消旧完整宿主的 Undici 初始化分支，不增加隐式代理切换。
7. Schema 采用 account_id/state_dir/command/target_id，成功回填 SDK 原始 accountId。旧 OpenClaw 或临时 WeClawBot-API 配置不会自动猜测迁移；首次通过网页重新登录并保存。
8. 前端删除第三方风险提示及其组件/测试，改为微信登录专用组件。README.md 与 plugins/channel/README.md 注明 corespeed-io/wechatbot，使用说明保留 Token 保存与 10 条回复硬限制。

## Validation

真实固定 SDK、模拟平台 HTTP 验证扫码/数字/刷新/0600/Token 不进 IPC/可重启使用凭据；真实 Node 进程验证 getUpdates、Manager 确认、SDK 游标/上下文持久化与通知回执/错误/不重试。后端与前端回归、类型/lint/build、网页桌面/移动 smoke、OpenSpec strict 与 diff 审查。真实账号认证由用户扫码完成，自动检查不向私人微信发消息。
