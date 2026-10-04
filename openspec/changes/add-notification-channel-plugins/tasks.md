# 实施任务

依据：[提案](proposal.md)、[设计](design.md)、[能力增量](specs/notification-plugins/spec.md)、[统一 ChannelManager 设计](../redesign-agent-channel-manager/design.md)。

当前状态：**2026-10-04 用户已确认并补充目录、logging 文件与删除全部原先预配置 Collector 的要求；开始实施。**

## 用户确认前的阻塞决策

- [x] 0.1 确认 Email 仅 SMTP 出站、`aiosmtplib`、TLS 默认 `starttls`、凭据引用、DATA 后不自动重试的方案。
- [x] 0.2 确认正式 file 能力名，标准 logging/FileHandler 追加日志、flush、相对 data_dir；不使用 JSONL。
- [x] 0.3 确认“微信小龙虾”是否指 OpenClaw Weixin/Tencent iLink，并确认允许采用 sidecar/bridge 而不是在 Python 中重写协议。

## 插件边界与公共接入

- [x] 1.1 在 `plugins/channel/<id>` 建立六个 channel 插件的清单、入口和最小注册代码；从核心 `src/logagent/channel` 移除具体平台/文件适配器。
- [x] 1.2 让插件发现按现有注册事务发布能力；缺失可选 SDK 只产生该插件诊断，不影响其他插件；校验 `notification` 与 `conversation` 能力矩阵。
- [x] 1.3 复用唯一 `ChannelManager`、统一队列和 Agent 端口；验证双向 SDK 回调只入队，单向 `send` 不创建 Agent 会话。
- [x] 1.4 为每个 SDK 建立受支持版本范围和可选依赖安装入口；不得在核心必需依赖中引入平台 SDK。

## 单向插件

- [x] 2.1 实现 Email 插件：`aiosmtplib` 常驻 SMTP 客户端、TLS/认证/收件人覆盖、30 秒发送预算、DATA 明确接受才成功、响应丢失时不确定且无隐式重试。
- [x] 2.2 实现文件插件：标准库 logging/FileHandler 追加 UTF-8 日志、共享 Handler 串行化、父目录创建、flush、handleError 错误传播及在途写入清理。
- [x] 2.3 对旧 `mock` 文件资源实施用户确认后的显式迁移；迁移保留路径、可重复、失败可诊断，不提供核心内置回退。

## 双向插件

- [x] 3.1 实现 QQ 插件：使用腾讯 `qq-botpy` 的 Gateway/事件/发送 API，覆盖好友、群和频道支持范围；验证原路由回复、重复事件和接收故障回执。
- [x] 3.2 实现微信 OpenClaw bridge 插件：固定 sidecar/IPC 契约、QR 登录状态、入站归一化和原路由回复；禁止复制 iLink 协议。
- [x] 3.3 实现飞书插件：使用 `lark-oapi` WebSocket 事件模式和官方发送 API；验证事件确认、会话目标和接收重连。
- [x] 3.4 实现 Telegram 插件：使用 `python-telegram-bot` Application long polling；验证 chat/user 身份、reply-to 路由、轮询停止和限流错误。
- [x] 3.5 为四个双向插件分别提供 SDK mock/contract 测试，并用真实 Manager/Agent 端口测试单向和双向路径不旁路。

## 预配置与验证

- [x] 4.1 删除 mock/logs/history Collector 的实现、默认注册和配送的 plugins/mock；删除 starter resources 中采集器、setter、旧 default_file/mock 种子；保留用户已有资源，更新创建新资源的测试夹具和文档。
- [x] 4.2 验证六个插件的能力描述、配置 schema、凭据不会泄露到日志或清单诊断。
- [x] 4.3 按目标单测 → 静态/类型检查 → 受影响包构建 → 最小 smoke test 验证；后端单测命令硬超时 60 秒。
- [x] 4.4 对照本变更 spec 和 design 审查 diff：确认核心没有平台协议、没有第二个 Manager、没有静默 fallback、没有重复 Agent 队列。

## 依据与暂定默认值

| 决策/默认 | 依据与理由 |
| --- | --- |
| `aiosmtplib` | 仓库已有直接依赖和 Email 实现；继续使用官方异步 SMTP，减少协议重复实现。 |
| Email 仅出站 | 用户明确将 Email 与本地文件排除在双向范围外；不增加 IMAP/POP 的连接、同步和安全边界。 |
| Email `tls=starttls` | 587 是常见提交端口；默认拒绝明文，465 通过显式 `implicit` 配置。 |
| Email DATA 后不自动重试 | SMTP 服务器可能已接受消息但响应丢失；重试会制造重复邮件，沿用现有“不确定”投递语义。 |
| 文件 logging | 用户明确要求 file 用 log；复用标准 FileHandler 的锁、编码、追加和 flush，handleError 必须传播错误。 |
| 不增加 fsync 参数 | 标准 FileHandler.flush 是成功边界；用户要求 logging，避免另写文件协议。 |
| 文件相对 `data_dir` | 沿用现有 `mock_file` 路径策略，避免不同插件拥有两套数据目录语义。 |
| QQ `qq-botpy` | 腾讯官方 Bot SDK 负责 Gateway、事件模型和发送协议，替代手写 HTTP/WebSocket。 |
| 飞书 `lark-oapi` WebSocket | 官方 SDK 负责鉴权、事件分发和类型化 API；WebSocket 不要求新增公网 Webhook。 |
| Telegram long polling | `python-telegram-bot` 官方异步 Application 直接支持；部署不需要额外公网入口。 |
| 微信 sidecar/bridge | OpenClaw Weixin 使用外部插件和 Tencent iLink；Python 内重写协议会重复造轮子且包名/版本仍有漂移。 |
| 无采集器 starter 资源 | 用户要求删除采集器相关预配置；只移除新建资源的种子，不删除已有用户资源。 |

## 文档验证记录

最终验证结果记录于本文末尾；实施中发现的旧测试导入、默认资源和平台协议断言同步迁移，不恢复被删除的核心具体实现。

## 2026-10-04 实施计划与依据

结构性调整：registry 只扫描根级插件，channel/__init__.py 注册具体内置渠道，collection/__init__.py 默认配送三类 Collector。须由唯一注册器支持分组目录，并删除具体内置实现。

涉及 registry、channel 装配、collection 导出、资源迁移、plugins/channel、可选依赖及测试。SDK 生命周期以安装版本源码为依据，不使用假定 sidecar 接口。验证依次为定向测试、Ruff、构建、最小插件及 Manager smoke，后端测试命令硬超时 60 秒。

## 接续实施中的证据与修正

- 默认 workflow 目标保留在实例配置；`split_options` 只投影账户字段会移除 Email recipient，实际冒烟复现后改为完整配置快照，飞书/微信同样修正。
- QQ 官方 `Client.start(ret_coro=True)` 已完成认证并提供 API；单向发送不运行 Gateway coroutine，关闭时显式 close 未调度的 coroutine。
- 删除核心 email/mock/qq/testing 具体实现；测试专用能力将保留于 tests fixtures，不恢复核心默认能力。
- 旧 `mock` 文件资源在现有 persisted-data migration 入口改为 `file`，数据结构及 format_version 不变，保留 ID/path/workflow 绑定；新 API 不接受 mock 别名。
- 微信冻结腾讯 npm `@tencent-weixin/openclaw-weixin@2.4.9` 与其支持的 OpenClaw 宿主 `2026.8.1`；随插件提供 bridge，复用包内 getUpdates、sendMessageWeixin、账户/上下文存储，无手写 HTTP/鉴权/iLink。来源为 npm 发布包 metadata 及其 dist/src 代码。
- 飞书安装 SDK 1.7.3 的同步 `ws.Client.start()` 使用模块全局 event loop，且没有公开 stop；接收生命周期正在按实际源码收口，不把取消 to_thread 当作停止成功。
- SDK callback 受理契约：`configure()` 注册的入口调用共用 `enqueue(wait_result=False)`，仅在唯一队列受理和 SQLite 消息身份 claim 成功后返回 accepted/duplicate。原程序调用和 Web 默认等待结果不变；`test_platform_admission.py` 用真实 AgentService 和阻塞端口验证受理不等待处理、去重、单向不创建会话及原路回复。
- 微信宿主 OpenClaw 2026.8.1 的 engines 要求 Node `>=22.22.3 <23 || >=24.15.0 <25 || >=25.9.0`；机器 Node 24.14 的 SQLite 版本被官方宿主拒绝。用临时 Node 24.15.0 和临时状态目录验证真实 SDK 导入，未登录账号显式返回 weixin_login_required，不绕过官方版本检查。
- 微信官方 npm 包中的模块路径随 2.4.9 固定；Node IPC 只做进程和受理 glue，不复制 HTTP、鉴权、长轮询或 cursor 存储。扫码登录由官方 CLI 执行，安装步骤、账户 ID 和状态目录在插件 README 中明确。
- 源码发行排除安装的 node_modules；初次 sdist 因遍历 851 MiB npm 依赖超时，显式配置 Hatch 排除后构建成功。wheel 保持核心包边界，六个插件和 Node bridge 随仓库/源码发行配送。
- `FileHandler` 的 TextIO 写入须返回完整字符数；缺失计数或短写按 EIO 报告不确定失败，依据迁移前的完整性用例，不把无法确认的写入记为成功。
- Telegram SDK 是成熟社区维护的 python-telegram-bot；QQ/飞书/微信采用平台官方 SDK，SMTP 采用现有 aiosmtplib。SDK 的官方性不影响插件边界或单/双向能力矩阵。
- QQ 固定 `qq-botpy==1.2.1`：该版本 `botpy.http.BotHttp.request` 在 `ConnectionResetError` 后递归重试，且没有关闭选项；适配器通过公开 `botpy.api.BotAPI(http=...)` 注入只拦截 POST 内部重试的子类。公开 `Client(log_level=...)` 用 `INFO` 禁止 SDK DEBUG 输出 Authorization 请求头。HTTP 401/403/404/405/429 按 SDK 的 `botpy.errors.HttpErrorDict` 映射为明确拒绝，500/504 与网络错误仍按不确定结果处理。依据是已安装 1.2.1 的 `botpy/http.py`、`botpy/api.py`、`botpy/errors.py` 和 `botpy/client.py`；`tests/channel/test_qq_sdk_contract.py` 用本地 aiohttp 服务验证真实 BotAPI HTTP 行为。

## 2026-10-05 完成与验证

六个插件及分组发现、Collector 删除、旧 mock→file 持久化迁移已完成。后续绑定行为以 [实例绑定设计](../bind-duplex-channel-conversations/design.md) 为准：此前记录的 enqueue(wait_result=False) 已被移除；现在 SDK enqueue 只受理，Web 自行等待已有操作结果。

- Email/File/ChannelManager/UnifiedQueue：89 passed；Workflow integration/disabled/overrides/config/resource-store：99 passed。
- 四平台适配器、真实 QQ HTTP contract、微信 Python IPC：18 passed；飞书真实 SDK 与生命周期：9 passed；微信 Node bridge：4 passed。
- plugin discovery、资源迁移、starter/source enabled：10 passed；Agent admission/service/HTTP API：39 passed。以上为各定向命令结果，不声称全仓测试通过。
- 飞书真实 lark-oapi 1.7.3 contract 发现 SDK 的 ExpiringCache._cron 也是独立任务；停止时与 WebSocket 接收/心跳一起取消并 gather，验证 cache task.done()，避免关闭专用 loop 时泄漏。
- Ruff、uv lock --check、前端类型/架构检查与生产 build、wheel/sdist build、两项 OpenSpec strict validate、git diff --check 均通过。源码发行核查六个 manifest 与微信 bridge 存在，node_modules 排除；QQ SDK 自动生成的 botpy.log 属测试产物，已忽略并清理，避免进入发行包。
- 真实认证后平台联调未执行；契约测试、真实 SDK 本地生命周期及本地 HTTP/IPC 已验证。未发送真实邮件或平台通知。
