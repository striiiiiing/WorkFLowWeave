# 插件加载与渠道启动失败隔离

## 依据与不变量

- 用户 2026-10-10 报告飞书 `timed out during opening handshake` 阻断后端启动，并明确要求所有插件符合“插件加载失败隔离”。
- 本变更 `design.md` 的内置/用户插件共用唯一 PluginRegistry，以及 `../redesign-agent-channel-manager/design.md` §3、§10 要求接收失败独立报告、不阻断 Web/test、收发能力独立、清理失败保留所有权。proposal.md/design.md 不修改。
- 根因：PluginRegistry 已逐插件回滚导入/注册异常；ChannelManager.configure 却在任一接收端失败时重新抛出，阻断 ApplicationLifecycle.start 或 reload。health 未读取接收启动错误。官方 SDK 1.4.0 的 ws/client.py 在握手失败后自动重连，所以首次握手错误日志不等于已向 Manager 抛出启动异常。
- 结构修复选用 Manager 统一隔离，而非给飞书加专用 bypass；应用启动、资源同步、插件重载遵循同一规则。仅插件注册视图发布等核心失败、取消和既有运行实例无法安全停止的情况仍按原契约报错；不把失败插件标记 ready，不修改持久化 enabled。
- 启动预算继续使用 ChannelConfig.timeout（默认 30 秒，来自 models.py 与上述设计），覆盖实例准备和接收连接；失败接收清理使用 Manager 已有 stop_timeout（默认 5 秒），不新增配置或无限后台重试。清理失败的实例保留引用并在再次接收前先重试清理，换账号配置也不能绕过旧资源清理。已失败的 stop task 释放后允许重新调用 stop；仍在运行的 stop task 继续保留，不启动重复清理。
- 启动错误保存在 Manager 单一运行态诊断中，通过已有 plugins.capability_errors 投影到健康接口/插件页；记录渠道类型、实例与静态错误消息，不输出插件任意异常文本、凭据或地址。成功恢复、禁用或删除后清除对应启动诊断；尚有清理失败资源时保留诊断，不假装已回收。
- 内置配送插件与用户插件的 channel/tool 两种类型沿用同一发现事务；核心 Web 声明、系统配置、存储及注册视图发布不冒充可选插件。

## 工作项与验证

- [x] 复现多个实例中的创建、初始化、接收失败/超时及取消行为。
- [x] 在 Manager 统一隔离、清理并记录接收启动失败；保留取消和清理失败的真实语义。
- [x] 接收失败进入可选插件降级诊断，健康仍允许其他功能；启动、重载、恢复走同一行为。
- [x] 覆盖内置/用户 channel/tool 插件导入和注册失败事务隔离。
- [x] 定向单测（每次硬超时 60 秒）、渠道/生命周期/插件回归、ruff、diff check、wheel 构建和本地 HTTP smoke。

## 验证边界

- 不使用用户真实账号发送消息，不更改 config.json 或资源库；本地故障注入不能证明飞书外网 WebSocket 已恢复。

## 验证记录

- `tests/config/test_config.py tests/config/test_plugin_failure_isolation.py tests/config/test_shipped_plugins.py`: 66 passed。
- `tests/channel/test_feishu_plugin.py tests/channel/test_first_message_connection.py tests/channel/test_channel_manager.py tests/channel/test_receiver_isolation.py`: 最终 78 passed。
- `tests/channel/test_receiver_isolation.py tests/config/test_plugin_failure_isolation.py tests/lifecycle/test_channel_startup_isolation.py tests/lifecycle/test_agent_channels.py::test_receiver_restart_failure_is_isolated_during_plugin_reload`: 最终 25 passed（与上述集合有交叉）。
- `tests/channel/test_agent_channels.py`: 20 passed。
- `ruff check`（本次修改的实现与测试文件）和 `git diff --check` 通过。
- `uv build --wheel --no-build-isolation --offline --out-dir /tmp/workflowweave-plugin-isolation-dist` 成功。从 wheel 解包目录通过实际 CLI 启动 Uvicorn，以未设置环境变量凭据的飞书实例验证失败隔离：`GET /api/health` 返回 200/degraded、accepting_runs=true；`POST /api/channels/web/commands` 返回 202 并创建真实本地会话。SIGINT 后日志确认 Application shutdown complete，CLI 返回 130（Ctrl-C）；未访问飞书网络。证据：`/tmp/workflowweave-isolation-smoke-z_a1es3x/backend-final.log`。
- 扩大生命周期集合未全绿：输出 18 passed / 18 failed，因失败测试未收尾引发日志资源串扰，进程最终被 60 秒硬超时终止。两类首要旧预期差异为回复地址多出 conversation_type=null，以及测试 fixture 将已配送插件再次复制到用户目录导致 plugin_id_conflict（另有旧测试仍预期仅注册 web）。在隔离导入目录恢复本次修改前的 manager.py/health.py 后，分别重跑 HTTP 地址断言和 plugin publish/reload 用例，均复现相同失败；未通过修改无关代码或吞错误把扩大集合伪造为通过。
