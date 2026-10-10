# 飞书迁移官方 Channel SDK

## 依据与决策

- 用户 2026-10-10 明确要求“飞书换成官方方案”。
- 参考同一变更 `design.md`：飞书继续使用官方应用机器人 WebSocket 长连接，双向消息仍由唯一 `ChannelManager` 接收入队。
- 官方迁移文档规定渠道机器人使用独立的 `lark-channel-sdk`，导入入口为 `lark_channel.FeishuChannel`；完整 OpenAPI 资源才继续使用 `lark-oapi`。依据：https://github.com/larksuite/channel-sdk-python/blob/main/docs/migration-from-lark-oapi.md 。
- `lark-channel-sdk==1.4.0` 的公开接口提供 `on("message", ...)`、`connect_until_ready()`、`disconnect()` 和 `send()`，因此删除插件对 `lark-oapi` 私有 WebSocket `_connect/_disconnect/_ping_loop` 的依赖。
- 保留项目自己的 `ChannelManager`、SQLite/入站去重、Agent 会话绑定、权限和投递回执；官方 SDK 的消息标准化和传输去重不替代这些业务边界。
- 为保持既有产品行为，构造官方 `PolicyConfig(require_mention=False, respond_to_mention_all=True)`，不额外增加群聊 @ 或 @全体 门槛；正式权限仍由项目 Manager 和资源配置控制。继续仅受理 `raw_content_type="text"`，避免把媒体占位符作为用户文本发送给 Agent。
- SDK 1.4.0 的 `channel/channel.py` 在自己的后台事件循环分发消息；适配器捕获应用循环并使用 `run_coroutine_threadsafe` 等待 Manager 受理，避免跨循环操作锁、队列与 SQLite。回调携带接收代次，停收前的旧回调不能进入新接收实例。
- 官方默认 `ChatQueueConfig(enabled=True, merge_while_busy=True)` 会合并连续消息（默认文本延迟 600ms）。设置 `ChatQueueConfig(enabled=False)`，使原始消息 ID 与逐条入队语义一致，队列仍由项目 Manager 唯一负责。依据：官方 1.4.0 的 `channel/config.py`、`channel/safety/pipeline.py`。
- 官方默认 `RetryConfig(max_attempts=3)` 和 `SendOpts.reply_target_gone="fresh"` 会重复尝试或降级原回复路由。设置 `max_attempts=1`、回复 `reply_target_gone="fail"`，依据本变更 design.md 的“失败显式报告且不自动重发”及原地址确认要求。SDK 失败回执中的超时/未知结果转换为 `uncertain=True`，并提取错误枚举 `.value`。
- 官方默认出站按 3500 字符拆分，可能先发出部分消息后只返回最后一次失败。设置 `text_chunk_limit=0`，保留既有单条投递语义；此值在官方 `outbound/sender.py:chunk_text` 中明确表示不拆分，平台长度限制仍显式报错。
- 独立审查发现 SDK 会将未分类的明确 API 拒绝归为 `UNKNOWN`，同时保留非零 `raw_code`。投递不确定性判断优先检查原始错误码，避免把明确拒绝误标为未知结果；依据官方 `channel/errors.py:classify_error`、`outbound/sender.py:_to_result`。回归测试已在修复前复现该误判。
- 连接失败或取消后移除订阅并调用公共 `disconnect()`，回收部分启动资源；`stop()` 仅在清理成功后标记关闭，清理错误不会被吞掉，可再次清理。删除已无调用方的旧 `channel/feishu_sdk.py` 加载器，不保留第二套 SDK 实现。

## 工作项

- [x] 将飞书可选依赖由 `lark-oapi` 切换为 `lark-channel-sdk==1.4.0`。
- [x] 用官方公共 Channel API 重写飞书插件适配层。
- [x] 保留现有资源 schema、首次私聊连接映射、发送/回复地址和 Manager 入站协议。
- [x] 安装真实 SDK，更新 uv.lock，运行飞书定向测试、渠道回归、lint、锁文件检查与 wheel 构建。
- [ ] 真实飞书账号验证 WebSocket 首次连接、私聊消息、回复和单向通知。

## 风险与验证边界

- 官方 SDK 保留传输去重和安全处理，当前适配器不把其内部状态写入项目数据库，项目数据库仍是 Agent 入站去重和投递状态的真源。SDK 默认的过期消息过滤等内部行为仍受官方实现控制。
- 官方 SafetyPipeline 的 SeenCache 始终开启，消息处理结束后会在 finally 中记为已见，即使应用回调受理失败也可能抑制平台重投。因此本次迁移不提供“受理失败后必定重投”的保证；此边界来自官方 SDK 1.4.0 的 `safety/pipeline.py` 和 `config.py`，未通过修改 SDK 私有实现绕过。
- PyPI 的 uv TLS 拉取曾失败；通过 curl 下载官方 1.4.0 wheel 并核对 PyPI SHA-256 后安装成功。实际导入与所有必需传递依赖版本检查通过。`uv lock --native-tls` 成功；锁文件仅将 lark-oapi 1.7.3 替换为 lark-channel-sdk 1.4.0，其他包版本不变。
- 飞书定向测试 20 passed，包含真实 SDK 本地公共生命周期、事件分发、逐条消息和实际 sender 的单次发送/原回复路由验证，以及未知 API 错误码的明确拒绝判断。网络账号调用在该本地测试中被替换，不能据此宣称真实 WebSocket 或平台投递成功。
- `timeout 60s .venv/bin/pytest -q tests/channel/test_feishu_plugin.py tests/channel/test_first_message_connection.py tests/channel/test_platform_admission.py tests/channel/test_channel_manager.py`：76 passed。跨平台入站回归改用官方标准化消息模型。
- 受影响三个 Python 文件 ruff 通过，`uv lock --check --offline` 通过，`git diff --check` 通过。`uv build --wheel --no-build-isolation --offline` 成功；检查 wheel 包含新飞书插件、正确可选依赖且不包含旧加载器。
- 将构建后的 wheel 实际安装到独立目录，从该安装位置导入飞书插件，使用占位凭据构造真实官方 SDK 并关闭成功；此 smoke 不调用平台网络。`uv sync --locked --extra channels --inexact --no-build-isolation --native-tls --link-mode copy` 最终成功，项目 editable 包和官方 SDK 1.4.0 已同步安装。
- 真实飞书账号 WebSocket、私聊首条消息及实际投递尚未验证；保持验收项未勾选。proposal.md/design.md 未修改。
