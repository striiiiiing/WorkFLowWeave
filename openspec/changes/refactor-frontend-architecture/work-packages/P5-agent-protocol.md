# P5 Agent 协议核心

根任务：[tasks.md §6](../tasks.md#6-p5--agent-协议核心)。依赖 P1；与 P2/P4 并行，结束后向 P6 移交 Agent 所有权。依据：[原设计](../../design-frontend-architecture/design.md) §7、§8.1、§12。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/LogAgent` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。worker 禁止切 branch、stash、reset 或 commit，只改获分配文件，公共文件请求唯一集成 worker 串行处理。主代理审查并提交本任务 diff，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 钩子。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 文件所有权与输出

写 `modules/agents/api/**`、`modules/agents/model/**`、`modules/agents/composables/useAgentSession.ts` 及协议/流/投影测试；迁移旧 useAgentStream 中传输/事件规则、components/agent/transcript.ts 与必要旧 API 出口。可保留连接旧页面的单一适配入口直到 P6，但不保留两套 reducer。P6 尚未启动时锁定 Api/DTO/event transport；P1 已移走的 DTO 不再复制。

transport 接收 EventSource/时钟工厂，负责 URL/游标/close/单一重连；model/events 验证信封与实际消费 payload，sessionProjection/transcript 纯转换。P5 同时按原设计 §7 提取 `composables/useAgentSession.ts`，通过注入 API/transport 唯一拥有历史→当前快照→SSE 顺序、generation、active turn 和游标接纳。P6 直接复用该控制器，不重写第二套生命周期或增加分包专用协调层。unknown 事件保留诊断，已知非法事件明确报错；原事件事实与展示投影只有一个转换来源。

顺序为历史→当前会话快照确定 active turn→从已接纳游标续传。按 `(session_id,id)` 去重，generation 隔离已过期连接，网络错误 close 后手动按 500–5000ms 退避重建；当前 turn 终态与旧 turn 终态分开，断线不取消后台。

## 协议与验证

命令执行 `/api/channels/web/commands`，SSE `/api/channels/web/sessions/{id}/events`，普通查询 `/api/agents/...`。request ID 与 payload 不变；停止独立于 send pending。文件 If-Match/If-None-Match、hash/ETag/冲突语义维持。后端仅作只读契约验证，记录测试当时 HEAD/dirty、实际导入路径与 channel 协议状态，对每条所需后端单测使用 60 秒硬超时。双向 channel 若改变端点/信封/事件而不兼容，明确记录差异和受影响用例；不改后端或加静默 fallback，继续可独立执行的前端针对性测试。

用旧事件样本验证同一投影输出，覆盖重连/重复/乱序迟到/旧终态/新一轮/解析失败。保留现有性能算法直到基线证明需要优化；即使优化也只有一个 reducer。HTTP/API 测试使用 P1 的受控 Axios adapter，不改为仅断言函数调用。

可先提交纯模型再提交 transport/useAgentSession，但 P6 前必须提供可运行旧 Agent 页和真实连接烟测。交接实际 transport/关闭语义、useAgentSession/reducer 类型与命令/文件 API 签名、测试样本和待删除旧适配；旧 useAgentStream 仅作为调用 useAgentSession 的薄适配，P6 完成后删除该适配。

## 实施证据

待填协议签名、契约结果与测试时后端 HEAD/dirty、明确协议差异、事件样本、浏览器结果和主代理 commit。
