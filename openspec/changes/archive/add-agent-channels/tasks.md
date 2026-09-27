# 双向渠道实施任务

依据：[proposal.md](proposal.md)、[design.md](design.md)，以及用户本轮追加的前端统一入口、双向仅 Agent、send 可供其他模块使用三项约束。

结构性问题：命令解析耦合 HTTP、仅有发送生命周期、没有外部会话身份。方案为抽出唯一 AgentChannel，扩展已有 Manager 与适配器能力，不另造插件注册或 Agent 循环。

- [x] 统一 Agent 命令、Web HTTP/SSE 和前端调用；旧端点作为兼容投影。
- [x] 扩展 conversation 契约、Agent 接收开关、常驻实例与回复发送。
- [x] 持久化外部会话绑定、去重及可观察的回复状态；装配生命周期与重载。
- [x] QQ 官方 Bot 收发适配器，凭据引用、协议测试。
- [x] 本地双向 test 渠道、HTTP 调试入口与真实 Agent 链路测试。
- [x] 定向单测、静态检查、构建、烟测及最终 diff 审查；未通过的全量检查与外部联调限制见下。

默认值依据：agent_enabled=false 保持既有单向资源行为；发送预算沿用 ChannelConfig.timeout=30 秒（models.py）；Web SSE 沿用 Agent 事件游标；QQ/test 仅最终回复以适应 IM 平台消息频控。接收没有额外整轮超时，模型预算仍由 Agent/AI 配置唯一决定（Agent design 的 300 秒流式空闲与 AI timeout）。

## 实施决策与依据

- 参考 `/mnt/d/code/QwenPaw/src/qwenpaw/app/channels/qq/channel.py` 的官方 Bot token、Gateway 和消息路由；复用本项目 CredentialManager、ChannelManager 和 AgentService，不引入第二个插件注册表或模型循环。
- QQ 成功回执的顶层 `id` 校验依据腾讯官方 Botpy 的 [api.py](https://github.com/tencent-connect/botpy/blob/master/botpy/api.py)（发送方法返回 Message）与 [gateway.py](https://github.com/tencent-connect/botpy/blob/master/botpy/types/gateway.py)（MessagePayload.id）；无可验证回执时保留未知状态，不自动重发。
- QQ 令牌提前 300 秒刷新、重连退避 1/2/5/10/30/60 秒沿用 QwenPaw 同文件的 token cache 与 RECONNECT_DELAYS；令牌有效期和心跳间隔必须由平台有效响应提供，不使用缺字段默认值。频道自身提及使用 READY.user.id，不假定等于 app_id。
- 接收开关由 ChannelManager 唯一校验，不进入常驻实例身份，允许同一个实例从 Workflow 单向发送切换为 Agent 收发。单向目标来自配置，回复目标来自固定的入站地址。
- `/stop` 绕过普通消息锁，并等待正在创建会话的消息完成准入后再次取消；只等待准入，不等待模型，避免首次消息取消落空。同一 peer 里此前排队的消息以 `message_interrupted` 结束；停止后的消息正常准入。停止代次在请求去重成功后才推进，旧 `/stop` 的重复投递不能取消后来排队的新消息。
- 关闭顺序为暂停 Agent、停止入站、关闭 Agent、排空回复、关闭绑定存储、停止适配器。排空预算 5 秒沿用 ChannelManager 的 `_STOP_TIMEOUT`，避免网络未结束而无限阻塞关闭；未确认投递记录为 `outcome_unknown / delivery_interrupted`，不伪造成功、不自动重发。
- 插件重载须先恢复接收器，再开放 Agent/Workflow 准入；恢复失败维持暂停，后续重载可以恢复。禁用/未启动/不存在等边界错误映射为明确 HTTP 状态，避免业务拒绝成为 500。
- 停止接收失败时保留旧配置和实例引用供下一次清理重试，只有成功停止后才删除运行时配置，避免遗留无法管理的监听器。
- test 单向目标默认 `local`，因为其出站仅记录到本地内存；真实模型执行、持久化绑定、去重和投递均经过生产链路。

## 验证记录（2026-09-23）

- 后端：`tests/channel/test_agent_channels.py tests/lifecycle tests/interaction tests/test_starter_resources.py`，111 项通过；覆盖真实 AgentService/LangGraph（仅模型使用 ScriptedModel）、会话隔离/恢复、原地址回复、Workflow 单向 send、HTTP、关闭和重载。
- 随后增加“接收恢复失败保持准入关闭”回归，`tests/lifecycle` 28 项全部通过。
- 最终准入代次、停止去重与接收清理修复后，runtime 与生命周期双向渠道测试合计 17 项通过；QQ 协议测试 17 项通过。
- `tests/channel` 最后一轮 114 通过、1 失败：旧 SMTP `accepted_drop` 用例只让出事件循环 5 次就断言连接已关闭，整组运行时该断言未稳定成立；此前一轮的旧 SMTP recipient 用例在 100 毫秒预算下出现不确定投递状态。这两个用例各自复测通过（recipient 所在参数组 4 项、accepted_drop 1 项），但不宣称全组稳定通过。本次未改 SMTP 实现或弱化其测试断言。
- 前端：`agent-channel-api`、`agent-stream`、`agent_chat`、`agent-view`、`resource-config`，27 项通过。验证所有对话操作走 Web channel、普通斜线文本不误解析，以及 SSE 重连游标。
- Ruff、Python `uv build`、前端 `npx vite build` 通过。
- 真实本地 HTTP 烟测：Web 新建/发送/SSE `turn.completed`；test 注入/Agent 执行/原地址回包/投递成功；重复请求不产生第二次发送，全部通过。使用临时数据和模型替身，没有调用真实 QQ。
- 前端全量 `vue-tsc --noEmit` 尚未通过：最近检查受并行工作中的 `ResourcesView.vue` 未使用 `WorkflowDefinition` 导入阻断；本任务不改写该页面。此前 CollectorDesignDemoView 类型错误已随并行变更消失。
- Tabbit 已尝试实际创建页面，但环境无窗口且 `Target.createTarget` 返回无法分发；未完成浏览器交互验证。QQ 尚无真实凭据联调，仅本地 HTTP/WebSocket 协议测试。
