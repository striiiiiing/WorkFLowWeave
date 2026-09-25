# P5 Agent 协议核心

根任务：[tasks.md §6](../tasks.md#6-p5--agent-协议核心)。依赖 P1；与 P2/P4 并行，结束后向 P6 移交 Agent 所有权。依据：[原设计](../../design-frontend-architecture/design.md) §7、§8.1、§12。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/LogAgent` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。新 worker 统一使用 GPT-6 Astra medium，只改获分配文件，禁止切 branch、stash、reset。普通实施 worker 禁止 commit；唯一获授权的集成 worker 串行处理公共文件、审查验证并精确提交，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 自动推送钩子，禁止 SKIP_WORKFLOW_PUSH 或覆盖 hooksPath。主代理仅编排和传递交接信息，不执行代码检查或验证。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 文件所有权与输出

写 `modules/agents/api/**`、`modules/agents/model/**`、`modules/agents/composables/useAgentSession.ts` 及协议/流/投影测试；迁移旧 useAgentStream 中传输/事件规则、components/agent/transcript.ts 与必要旧 API 出口。可保留连接旧页面的单一适配入口直到 P6，但不保留两套 reducer。P6 尚未启动时锁定 Api/DTO/event transport；P1 已移走的 DTO 不再复制。

transport 接收 EventSource/时钟工厂，负责 URL/游标/close/单一重连；model/events 验证信封与实际消费 payload，sessionProjection/transcript 纯转换。P5 同时按原设计 §7 提取 `composables/useAgentSession.ts`，通过注入 API/transport 唯一拥有历史→当前快照→SSE 顺序、generation、active turn 和游标接纳。P6 直接复用该控制器，不重写第二套生命周期或增加分包专用协调层。unknown 事件保留诊断，已知非法事件明确报错；原事件事实与展示投影只有一个转换来源。

顺序为历史→当前会话快照确定 active turn→从已接纳游标续传。按 `(session_id,id)` 去重，generation 隔离已过期连接，网络错误 close 后手动按 500–5000ms 退避重建；当前 turn 终态与旧 turn 终态分开，断线不取消后台。

## 协议与验证

命令执行 `/api/channels/web/commands`，SSE `/api/channels/web/sessions/{id}/events`，普通查询 `/api/agents/...`。request ID 与 payload 不变；停止独立于 send pending。文件 If-Match/If-None-Match、hash/ETag/冲突语义维持。后端仅作只读契约验证，记录测试当时 HEAD/dirty、实际导入路径与 channel 协议状态，对每条所需后端单测使用 60 秒硬超时。双向 channel 若改变端点/信封/事件而不兼容，明确记录差异和受影响用例；不改后端或加静默 fallback，继续可独立执行的前端针对性测试。

用旧事件样本验证同一投影输出，覆盖重连/重复/乱序迟到/旧终态/新一轮/解析失败。保留现有性能算法直到基线证明需要优化；即使优化也只有一个 reducer。HTTP/API 测试使用 P1 的受控 Axios adapter，不改为仅断言函数调用。

可先提交纯模型再提交 transport/useAgentSession，但 P6 前必须提供可运行旧 Agent 页和真实连接烟测。交接实际 transport/关闭语义、useAgentSession/reducer 类型与命令/文件 API 签名、测试样本和待删除旧适配；旧 useAgentStream 仅作为调用 useAgentSession 的薄适配，P6 完成后删除该适配。

## 实施证据

### 实际实现与交接签名

- `createAgentEventSource(sourceFactory?, clock?)` 返回 `open(sessionId, after, handlers)`, `accept(cursor)` 和 `close()`；它只负责 EventSource URL、游标、主动关闭和 500/1000/2000/4000/5000ms 手动退避。网络错误先 close 当前源，再重建；解析失败通过 `error` 结束当前连接。
- `parseAgentEvent(value)` 验证事件信封及已知事件消费字段；未知类型保留原始 `AgentEvent` 供诊断。`mergeAgentEvents` 以 `(session_id,id)` 去重并保持首次出现顺序。
- `projectAgentSession(session,event)` 是唯一会话投影：只更新当前 `turn_id` 的 budget、resources 与终态；`turn.started` 仅允许从非 running 状态建立下一轮，旧轮终态不能结束新轮。
- `useAgentSession(api, transport?, onEvent?)` 持有 `events/session/state/error/cursor`，公开 `select/resume/clear`。`select` 严格执行 history → current session → SSE；每次选择/清理递增 generation 并 abort 旧查询，接纳事件后推进 cursor。旧 `useAgentStream` 只保留此控制器的过渡适配，P6 删除适配后不需要迁移第二套 reducer。
- `agentsApi` 继续由 P1 单一 HTTP 工厂提供；命令使用 `/channels/web/commands`，普通查询和文件使用 `/agents/...`，文件写入保持 `If-Match`/`If-None-Match`。

### 后端契约核对

2026-09-26 只读核对时 HEAD 为 `7012a20`；工作区同时存在其他任务的后端 dirty 修改（`src/logagent/**`、`tests/**`、`pyproject.toml`、`uv.lock` 等），未暂存、覆盖或提交。本包没有改变后端。

- `tests/interaction/test_agent_api.py::test_agent_session_message_and_replay_endpoints`：`timeout 60s`，通过。
- `tests/interaction/test_agent_api.py::test_real_sse_disconnect_keeps_turn_running_and_replays_its_completion`：`timeout 60s`，通过。
- 实际路由同时暴露 `/api/agents/sessions/{id}/events` 与 `/api/channels/web/sessions/{id}/events`；前端命令入口使用后者，SSE 信封包含 `id/session_id/turn_id/type/at/data`，后端历史文件还保留扁平字段。前端只依赖 `data`，没有增加兼容 fallback。

### 测试证据

- 针对性 Agent 测试：35 项通过；新增协议模型/投影/游标/旧终态/迟到回调/非法已知事件/未知事件/文件条件写入覆盖。
- 全量前端单测：41 个测试文件、198 项通过。
- `npm run typecheck`、`npm run format:check`、`npm run architecture:check`、`npm run build` 均通过；`git diff --check` 通过。
- GPT-6 Luna 真实 Chromium 验收：`rtk npx playwright test --config=playwright.agent.config.ts --reporter=line`，2 项通过、0 项失败、25.181s。覆盖真实消息发送、终态、SSE 全量与游标回放、文件 ETag 冲突、375px 无横向溢出和慢模型 stop 取消；Vite、临时 FastAPI 与 Chromium 均实际启动，测试结束后 13001/14301 无残留监听。

### 提交与 P6 交接

- `7012a20 refactor(frontend): centralize Agent event session protocol`：P5 模型、transport、`useAgentSession`、旧页面适配、协议测试。
- 后续测试支撑修正待提交：真实 `ApplicationLifecycle` smoke 夹具、当前“工作区文件”按钮、条件写入头和稳定 stop 选择器；该提交只包含 `frontend/tests/**`。
- P6 复用 `useAgentSession` 的状态与签名，继续使用 `modules/agents/model/transcript.ts` 和 `projectAgentSession`；待删除 `frontend/src/composables/useAgentStream.ts` 与 `frontend/src/components/agent/transcript.ts` 过渡 re-export。P6 不应重新实现历史/SSE/reducer，也不应在页面中直接读取或转换事件 payload。
