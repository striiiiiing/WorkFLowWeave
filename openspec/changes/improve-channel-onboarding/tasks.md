# 实施任务

依据：[proposal.md](proposal.md)、[design.md](design.md)、[能力增量](specs/channel-onboarding/spec.md)。2026-10-07 用户确认网页内直接扫码登录，并要求先写 OpenSpec 后实现；既有通知插件设计不修改。

- [x] 1.1 记录用户遇到的 QQ 首次互动、SMTP 说明、微信登录与硬限制、path 示例问题，完成本变更设计。
- [x] 2.1 Email/QQ/微信/file schema 备注及 title，保留 password/host/port 配置兼容；凭据草稿保留 title。
- [x] 2.2 可选插件 start_login 注册与 Web 登录会话委派/关闭；禁止核心导入具体微信 SDK。
- [x] 2.3 Node 官方 SDK 登录、PNG 二维码、数字确认、刷新事件、300 秒预算、成功持久化及脱敏 IPC。
- [x] 2.4 网页微信专用登录区域、轮询、数字确认、取消/刷新、回填与配置变更失效处理。
- [x] 2.5 更新通知插件 README 的 Gmail、QQ、微信登录和文件示例。
- [x] 3.1 后端/Node 定向契约与前端状态测试，命令依据及结果记录于下方。
- [x] 3.2 类型/lint、构建、浏览器 smoke、OpenSpec strict validate、diff 审查。

## 决策依据

- title 是 JSON Schema 标准展示元数据；ParameterInput.label 是现有统一标题入口，credentialDraftSchema 须保持 title，避免增加第二套字段名称表。
- 微信 SDK 2.4.9 auth/login-qr.js 的 ACTIVE_LOGIN_TTL_MS=300000；轮询含 need_verifycode/expired/scaned，必须支持网页数字确认及新二维码。不能通过手写 iLink HTTP 替代 SDK。
- 官方 gateway.loginWithQrWait 的保存异常被 SDK catch，故实现使用 auth 登录函数与账户 save/register 函数显式保存，失败不可返回成功。账号 ID 使用宿主 normalizeAccountId。
- Token 本地路径来自 auth/accounts.js：状态目录/openclaw-weixin/accounts/<account_id>.json，官方写入权限 0600；账户索引 accounts.json。
- file 相对路径依据 src/workflowweave/config/normalize.py 的 x-workflowweave-path 归一化；验证通过真实临时 data_dir 写入该示例，不向用户运行数据写测试通知。
- 官方 SDK 真实契约测试首次耗时 40.6 秒，其中包含冷加载与 3 次状态轮询。HTTP 创建会话在进程启动后立即返回等待状态，SDK 冷加载计入总预算 300 秒；SDK 加载完成的 IPC 状态到首个二维码之间使用设计规定的 30 秒预算，避免把模块加载误判为平台 QR 获取超时。
- 安装微信 Node 依赖后，原 install_plugin 测试夹具复制整份 node_modules，导致插件注册回归命令达到 60 秒硬超时；夹具只安装插件源码，排除 node_modules，符合现有源码发行排除依赖目录的规则。Node SDK 契约直接使用仓库插件的独立依赖。
- 真实二维码请求的首轮失败为官方 SDK 的 UND_ERR_CONNECT_TIMEOUT；当前环境存在 HTTP_PROXY/HTTPS_PROXY，但 Node 未启用环境代理。验证服务显式设置 NODE_USE_ENV_PROXY=1 后能访问 iLink；README 记录这个可选部署设置，生产插件不增加隐式代理切换。
- SDK 宿主加载后有独立 Undici dispatcher，NODE_USE_ENV_PROXY=1 的 Node 原生 fetch 连通不等于 SDK 连通；登录进程仅在显式设置该变量时调用官方 infra-runtime.ensureGlobalUndiciEnvProxyDispatcher 初始化宿主网络，不复制代理协议或增加自动重试。
- 合并定向验证发现旧 Email accepted_drop 测试依赖五次 sleep(0) 等待断链，在负载下尚未收到 EOF 就执行 QUIT；经既有 client_factory 注入真实 SMTP 子类，在 _on_connection_lost 完成后发出 asyncio.Event，测试在硬预算 1 秒内等待该事件。没有轮询或固定事件循环次数。Email 投递/关闭逻辑保持不变，仍显式报告关闭错误。
- Gmail SMTP 信息依据 https://support.google.com/mail/answer/7126229；应用专用密码依据 https://support.google.com/accounts/answer/185833；示例均为说明，不提供真实授权码。

## 验证记录

2026-10-07 完成。全部后端命令使用 timeout 60s；为确保单条命令满足硬预算，最终回归按以下两组执行：

- `.venv/bin/pytest -q tests/channel/test_email_channel.py tests/channel/test_channel_login.py tests/channel/test_file_channel.py`：52 passed，26.48 秒。包含真实 SMTP 断链/重连、登录 API、状态/取消/超时与真实 data_dir 文件写入。
- `.venv/bin/pytest -q tests/channel/test_wechat_plugin.py tests/config/test_notification_plugin_discovery.py tests/config/test_plugin_setting.py tests/config/test_shipped_plugins.py tests/config/test_plugin_manifest_compat.py tests/interaction/test_interaction.py`：46 passed，15.82 秒。两组共 98 项；仅有既有 Starlette/AnyIO 弃用提示。
- 插件目录 `node --test bridge.test.mjs login.test.mjs login-sdk.test.mjs`：8 passed，22.99 秒。使用兼容 Node 24.15.0，真实官方 SDK 加模拟平台 HTTP 验证数字确认、二维码刷新、规范化账号、Token 本地持久化/0600 权限及 IPC 不含 Token；不是实际账号认证。
- 前端定向单测组合：25 passed；补充授权码展示断言后，resource-config/wechat-login 两组 10 passed。微信状态测试覆盖成功回填、数字确认、卸载旧响应、状态目录变更和错误。
- 前端 `npm run typecheck`、`npm run build`、`npm run architecture:check` 及改动文件 Prettier 检查通过；改动 Python 文件 Ruff 检查通过。
- Playwright `playwright.onboarding.config.ts`：模拟平台的网页契约检查通过；真实 iLink 网络 smoke 通过（47.8 秒），实际获取二维码、图片加载及链接展示，并在 1440/390 视口验证无横向溢出与取消。截图已人工检查。真实账号未扫码，未宣称认证完成。
- `openspec validate improve-channel-onboarding --strict` 与 `git diff --check` 通过。差异审查确认核心仅委派插件登录、没有手写平台认证、没有 Token 回传或隐藏网络降级。
- 隔离的 4311/4312 后端及 3002/3003 前端测试服务已关闭；用户原有运行服务未重启。新扫码 API 需重启后端后使用，登录成功还需点击保存资源。

以上 shell 命令均通过 rtk 执行。当前默认 Node 24.14.0 不满足官方宿主版本要求，验证使用兼容 Node，网页 command 字段也注明版本要求；没有替换用户默认 Node。
