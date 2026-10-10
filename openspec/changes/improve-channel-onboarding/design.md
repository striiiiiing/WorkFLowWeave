# 设计：频道初始化与微信扫码登录

## Context

沿用 [通知插件设计](../add-notification-channel-plugins/design.md) 的插件边界及 SDK 选择。现有微信 bridge 只接受已登录 account_id；官方 @tencent-weixin/openclaw-weixin@2.4.9 提供 startWeixinLoginWithQr、waitForWeixinLogin、saveWeixinAccount/registerWeixinAccountId。登录轮询会要求数字确认并自动刷新二维码，不能仅给出初始链接后等待成功。

## Decisions

这是跨插件注册、HTTP、进程生命周期与前端状态的结构性变更。仅增加备注可以解决 SMTP/QQ/file 说明，但无法满足网页微信登录；因此复用官方 SDK 并新增可选登录接口。

1. ChannelType 可选提供 start_login(options)；注册视图捕获这个异步接口，核心仅委派，不导入微信具体类。Web 应用持有登录会话管理器并在关闭时停止登录进程；登录不启动通知接收、不创建 Agent 会话、不要求先保存渠道。
2. API 使用 POST /channels/login/{capability} 创建会话、GET /channels/login/sessions/{id} 查询、POST .../{id}/verify 提交数字、DELETE .../{id} 取消。输入只接收非秘密 command/state_dir 配置；数字仅接受数字字符串。响应只包含会话 ID、状态、二维码链接/位图、账号 ID、消息及非秘密有效配置，Cache-Control 为 no-store。
3. 每次微信登录使用独立 Node 进程，复用固定版本官方 SDK 登录与账号持久化函数。SDK 的终端数字提示/二维码刷新输出转成明确 IPC 事件；stdout 专用于 JSON 事件，SDK 日志不透传网页。二维码通过 qrcode 标准库生成 PNG data URL，不重写编码。
4. 成功必须同时确认 SDK 返回 Token、账号 ID，并完成 saveWeixinAccount、registerWeixinAccountId；保存失败显式失败。Token 不经过 Python API/网页，不保存到 resources.json。网页只回填规范化 account_id 和本次登录 state_dir/command。
5. 选择微信时显示专用登录区域；状态包括等待扫码、已扫码、等待数字、成功、失败。刷新先取消旧会话；修改登录目录/Node 命令或关闭编辑页取消旧进程；避免旧请求回填新配置。登录成功后用户仍需保存渠道。
6. Email schema 用 title 展示授权码等名称，凭据草稿转换保留 title；host/port/password 键保持兼容。Gmail 587/starttls 与 465/implicit 在各字段备注说明，授权码示例为 Google 应用专用密码而非真实秘密。
7. QQ 明示首次互动由用户完成且仍受权限/时效约束；file 示例 logs/notifications.log，由现有路径归一化相对 data_dir 解析并由 FileHandler 创建目录和追加。

## Defaults And Lifecycle

- 扫码总预算 300 秒：依据官方 login-qr.js 的 ACTIVE_LOGIN_TTL_MS=5*60_000，不能沿用通知发送的 30 秒。
- 初次二维码等待 30 秒：沿用现有频道启动预算量级，启动失败/缺少依赖及时报错。
- 网页查询间隔 1 秒：与官方 SDK 轮询周期一致；只查本地会话，不重复发起平台轮询。
- 子进程停止预算 5 秒：沿用现有微信 bridge 的 _STOP_TIMEOUT；超时后 kill 并等待回收。
- 同一 OpenClaw 状态目录只允许一个进行中的登录会话，避免官方账号文件并发写；冲突显式返回，不自动取消另一页面。

## Validation

先验证登录状态/错误/取消/保存契约及 HTTP 脱敏，再运行前端状态测试、类型/lint、构建和实际浏览器 smoke。后端单测每次命令硬超时 60 秒。真实扫码确认由用户完成，自动验证不能宣称真实账号登录成功。
