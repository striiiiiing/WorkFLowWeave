# ChannelManager 重设计实施任务

依据：[用户需求与问题](proposal.md)、[本轮设计](design.md)、[源码参考](references.md)。以下状态记录本轮后端实施与验证；旧 [add-agent-channels/tasks.md](../add-agent-channels/tasks.md) 保留原状，旧代码和旧测试结果不计作新任务完成。

用户追加约束：禁止修改前端。所有 `frontend/` 文件均不属于本任务的编辑范围；Web 通过后端兼容现有协议完成渠道化，不新增前端任务。

## 1. 契约与唯一所有权

- [x] 1.1 在 `channel/conversation.py` 定义不透明平台路由、规范化输入、请求回执与处理事件；去除通用地址中 QQ/test 专用枚举。
- [x] 1.2 新增 `channel/base.py`，实现 process 事件消费和呈现/回复流程；通过注入依赖调用 Agent，禁止导入具体 AgentService。
- [x] 1.3 明确 ChannelConfig.agent_enabled 与 notification/conversation 能力；注册表保留单一来源和现有两参数工厂，装配保留 Web 实例。

## 2. 队列、停止与会话

- [x] 2.1 新增 `channel/unified_queue_manager.py`，由 Manager 唯一持有；实现每键单消费者、明确容量拒绝、逐条消费及活动感知清理。
- [x] 2.2 实现跨优先级的会话切换屏障与 stop 截止序号，使用可控事件测试首次创建、等待准入、活动回复和重复 stop 的竞态。
- [x] 2.3 将 `channel/agent.py` 的命令语义迁至 `agent/channel.py` 的处理端口；共享分类表，普通输入流等待轮次终态，安全边界命令只跟踪自身生效结果。
- [x] 2.4 在 AgentService 现有同步原语中提供可取消的等待空闲后原子准入；验证 Web/QQ 两个队列指向同一 session 时不会同时启动模型，不创建第二份模型队列。
- [x] 2.5 从 `channel/bindings.py` 提取绑定与回执存储接口，保留原 SQLite 数据并给出可重复执行的版本迁移；验证旧摘要身份的显式映射、未映射数据保留、跨版本去重及 QQ app_id 隔离。绑定归端口，回执归 Manager，Agent 正文不复制。
- [x] 2.6 实现唯一请求键、稳定 Agent request/operation ID、容量预留与发布、崩溃窗口核对；既有回执能读取，旧未知请求不自动执行或发送。

## 3. Manager 和生命周期迁移

- [x] 3.1 把 `channel/runtime.py` 的入站配置、任务和停止协调迁入 ChannelManager；删除 AgentChannelRuntime 及独立配置同步订阅，不能保留转发壳作为第二个运行时。
- [x] 3.2 统一 reply/send 的发送执行器，验证原地址回复、旧 Workflow 快照目标、timeout 与 DeliveryResult 保持原语义。
- [x] 3.3 更新 `lifecycle/services.py`、`lifecycle/service.py` 及 app 装配；ApplicationServices 仅保留唯一渠道 Manager 和 Agent 服务依赖。
- [x] 3.4 实现接收代次、停止旧监听后启新监听、在途旧实例租约、失败清理引用及健康状态；保留插件活动冲突规则。
- [x] 3.5 验证禁用 Agent 接收与 QQ Gateway 故障均不直接禁止独立单向 send，全局关闭按设计结算队列/取消/发送/存储。

## 4. 三种具体渠道及后端接口兼容

- [x] 4.1 新增 `channel/web.py`，使 HTTP 输入真正进入 Manager；请求查询和 SSE 通过该实例与注入端口，不直接 dispatch Agent。
- [x] 4.2 更新 `interaction/channel_routers.py` 和 `agent_routers.py`，在后端等待内部回执并保留现有响应字段和状态码；消息成功响应必须有真实 turn_id，新旧路由使用同一会话队列。
- [x] 4.3 增加 Python 后端契约测试，使用现有前端的原请求验证 action/session/request_id、kind/result、TurnAccepted/AgentSession、原 SSE 信封和游标均兼容；不改前端源码或测试。
- [x] 4.4 保留并适配 `channel/qq.py` 的官方协议实现，所有收消息走 enqueue，所有 Agent 消费走 Base，最终回复固定原路由。
- [x] 4.5 适配 `channel/testing.py` 和 `interaction/test_channel_routers.py`，提供 inject/outbox/outcome 的真实 Manager 闭环及可控传输错误。
- [x] 4.6 编写新版使用文档；旧 [usage.md](../add-agent-channels/usage.md) 不得被当作新版 API 契约。真实 QQ 联调在具备凭据及平台授权时单独记录。

## 5. 验证与审查

- [x] 5.1 目标单测：Web/QQ/test 入站均触发同一 Manager/QueueManager 消费；双向消费者只能为 Agent；单向调用不触发队列或 Agent。
- [x] 5.2 并发单测：普通消息 FIFO、QQ/test 的 A/B/new/C 屏障、Web 显式目标不改投、append/compact 可先作用于 A 而 B 仍等待、stop 首条竞态与重复去重、多来源同 session 单轮、满载、长任务不被回收。
- [x] 5.3 持久化/生命周期单测：重复冲突、账号替换不串消息、旧快照发送、入队/执行/发送崩溃窗口、未知结果不重试、清理失败可重试。
- [x] 5.4 QQ 协议测试和 test 端到端：保留既有 token/Gateway/ACK/REST 用例，增加队列受理与平台错误回执检查；只替换模型/网络，保留真实 AgentService。
- [x] 5.5 后端集成测试：Web 排队时 HTTP 等待、真实 turn_id 后响应、SSE 订阅前已完成的轮次、多页签同 session、重复提交、断连不取消、普通斜线文本、原端点和渠道端点 stop 互通。
- [x] 5.6 按目标单测 → 静态检查 → 受影响包构建 → 最小 HTTP/浏览器烟测顺序验证；每条后端单测命令硬超时 60 秒。
- [x] 5.7 最终对照 design/spec 审 diff：删除独立 runtime、HTTP 旁路、重复解析/任务表、隐式成功/丢弃/重试；记录真实 QQ 未联调等限制。

## 默认值与决策依据

| 决策/默认 | 理由和依据 |
| --- | --- |
| agent_enabled=false | 保留旧资源仅发送行为；旧 Channel 设计不自动连接接收端 |
| 优先级 0/10/20、每键一个消费者 | QwenPaw CommandRegistry/QueueKey；同键有序，stop 能独立调度，跨键 Agent 单轮另由原子准入保证 |
| 每键待处理容量 1000 | QwenPaw UnifiedQueueManager 的现有默认；不是全局容量上限，不能据此声称总内存有界 |
| 入队不等待容量，满载立即拒绝 | 与参考的 30 秒等待不同；避免 HTTP/Gateway 持有大量等待入队任务，并给调用方明确受理语义 |
| 首版不批量合并、不防抖 | 每请求独立去重、回执与原消息关联；当前需求没有要求媒体聚合，参考合并失败行为会丢消息 |
| 队列清理间隔 60 秒、空闲阈值 600 秒 | 采用参考值，降低反复创建消费者成本；增加活动/屏障判断，不能用空队列推断空闲 |
| Web HTTP 等待实际准入后响应 | 用户禁止修改前端；当前 agentsApi.send 和 useAgentStream.resume 依赖真实 turn_id，不可改为 nullable turn_id 或要求客户端轮询 |
| 单次发送 timeout=30 秒 | 沿用 ChannelConfig.timeout，覆盖一次发送全流程；不作为模型或排队上限 |
| 渠道清理预算 5 秒 | 沿用 ChannelManager._STOP_TIMEOUT；只约束渠道清理等待，Agent 资源释放仍按其自身契约 |
| 不新增 Agent 整轮超时 | AgentConfig.idle_timeout=300 秒是流式无事件预算，不是整轮执行上限；不能因消息在队列中等待超过该值就丢弃 |
| QQ token 提前 300 秒刷新、重连 1/2/5/10/30/60 秒 | 保留上一版基于 QwenPaw QQ 实现的协议参数；有效期/心跳间隔仍必须来自有效平台响应 |
| QQ 每轮最终回复 | 保留平台回复关联并避免 token 级发送触发频控；命令的生效结果单独关联命令，不重复发送整轮文本 |
| test 单向目标 local，outbox 内存保存 | 调试输出不依赖外部账号；绑定/回执仍持久化，outbox 重启清空必须明确 |

## 本轮文档验证

2026-09-24：`openspec validate redesign-agent-channel-manager --strict --no-interactive` 通过；7 个 Markdown 文件的引用、代码围栏和空白检查通过；27 条实施任务编号唯一且均未勾选，禁止前端修改的范围检查通过；`git diff --check` 通过。

设计复核已明确 append/compact 可先于等待中的普通消息作用于活动轮次；用户追加禁止前端修改后，Web 改为后端兼容现有显式 session、kind/result 和 SSE，不要求前端维护新的对话标识或请求状态。

本轮只修改设计与任务文档，没有修改前端或后端代码，因此不运行业务单测/构建，也不把上一版的测试结果计入本次验收。文档齐备和 OpenSpec 校验通过不表示上面的实施任务完成。

## 后端实施记录（2026-09-25）

以上审计记录保留 2026-09-24 的历史状态。本轮已按本文件任务实施后端，未修改 `frontend/`。主要证据如下：

- `src/workflowweave/channel/manager.py` 现在拥有唯一入站队列、接收代次、去重、绑定回执、Web 投影、回复/单向发送和生命周期；旧 `AgentChannelRuntime` 已删除。
- `src/workflowweave/channel/unified_queue.py` 实现每对话消费者、stop/command 屏障、容量拒绝、活动感知清理和关闭；`src/workflowweave/channel/base.py` 只等待 Agent 终态并呈现结果。
- `src/workflowweave/channel/web.py`、`qq.py`、`testing.py` 均通过 Manager；`tests/channel/test_qq_channel.py` 新增模拟 Gateway/REST + 真实 Manager/AgentService 的闭环，验证重复消息去重及 QQ 失败回执。
- `src/workflowweave/channel/bindings.py` 增加旧身份冲突校验、稳定 operation 元数据和恢复查询；Agent 事件日志只在有证据时恢复会话/轮次，未知窗口不自动重放。
- 插件重载会检查渠道活动消费和发送；`tests/lifecycle/test_agent_channels.py` 覆盖回复在途冲突、多来源同 session stop 准入竞态。

2026-09-26 最终复验：`timeout 60s uv run --frozen pytest -q tests/channel tests/lifecycle/test_agent_channels.py tests/interaction/test_agent_api.py tests/interaction/test_collection.py` 为 179 项通过；受影响文件 Ruff、`uv build`、`git diff --check` 和 OpenSpec 严格校验通过。stop 穿过首次 session 绑定的用例依据 [design.md 的停止竞态契约](design.md) 改为断言“提交前阻止执行”：Agent 原子准入检查 stop 代次后返回 `message_interrupted`，会话不启动模型；活动轮次取消仍由独立用例验证。真实 QQ 平台仍未联调，原因是本地没有用户凭据和平台授权；协议使用模拟 Gateway/REST 验证。下方 2026-09-24 审计仅记录实施前历史状态，不表示当前后端实现状态。

## 后端实现审计（2026-09-24）

结论：**新版重设计尚未实现**。当前代码仍是上一版结构：`ChannelManager` 只提供实例缓存、单向 `send`、`start_receiving` 和 `stop_receiving`；没有 `enqueue`、`UnifiedQueueManager`、Manager 消费者或统一 `reply`。双向路由、去重、停止栅栏、入站任务和回复任务仍由独立 `AgentChannelRuntime` 持有。

证据：

- [src/workflowweave/channel/manager.py](../../../src/workflowweave/channel/manager.py) 的 `start_receiving` 只把 handler 挂到渠道实例，`send` 才调用 Manager 的发送执行器；文件没有新版所需 `enqueue`/队列消费者。
- [src/workflowweave/channel/runtime.py](../../../src/workflowweave/channel/runtime.py) 仍创建 `_incoming`、`_replies`、`_stop_fences` 和配置同步任务，并直接调用 Agent 命令端口。
- [src/workflowweave/interaction/channel_routers.py](../../../src/workflowweave/interaction/channel_routers.py) 及 [src/workflowweave/interaction/agent_routers.py](../../../src/workflowweave/interaction/agent_routers.py) 仍调用 `AgentChannel.dispatch`，没有通过 WebChannel 入 Manager 队列。
- [src/workflowweave/lifecycle/service.py](../../../src/workflowweave/lifecycle/service.py) 和 [src/workflowweave/lifecycle/services.py](../../../src/workflowweave/lifecycle/services.py) 仍分别装配并暴露 `agent_channel`、`agent_channels`；独立运行时尚未删除。
- [src/workflowweave/channel/conversation.py](../../../src/workflowweave/channel/conversation.py) 的通用地址仍将 `kind` 限定为 `c2c/group/guild/dm/test`，尚未迁移为平台不透明路由。
- [src/workflowweave/agent/service.py](../../../src/workflowweave/agent/service.py) 的普通 `submit` 仍在活动轮次时返回 `session_busy`；新版要求由 Manager 队列等待普通消息，不能将该错误作为排队行为。

验证：`timeout 60s uv run --frozen pytest -q tests/channel/test_agent_channels.py tests/channel/test_qq_channel.py tests/lifecycle/test_agent_channels.py tests/interaction/test_agent_api.py` 为 43 项通过；针对 Web 斜线文本、QQ resident receiving、test 原路回复/单向发送的 3 项定向测试通过；`ruff check` 对相关后端模块通过。这些测试验证的是旧版实现和兼容行为，不能勾选本任务 1–5 的新版实施项。全程没有修改 `frontend/` 文件。
