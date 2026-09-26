# P7 集成与最终验证

根任务：[tasks.md §8](../tasks.md#8-p7--集成清理与整体验收)。依赖 P3/P4/P6 全部完成并提交。依据：[原设计](../../design-frontend-architecture/design.md) §9–§12。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/LogAgent` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。新 worker 统一使用 GPT-6 Astra medium，只改获分配文件，禁止切 branch、stash、reset。普通实施 worker 禁止 commit；唯一获授权的集成 worker 串行处理公共文件、审查验证并精确提交，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 自动推送钩子，禁止 SKIP_WORKFLOW_PUSH 或覆盖 hooksPath。主代理仅编排和传递交接信息，不执行代码检查或验证。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 所有权与收口

GPT-6 Astra medium 集成 worker 在锁定范围内修改 app/router/bootstrap、跨模块 ContinueInAgent、公共配置/规则与最终 E2E；主代理只负责协调与汇总交接，专职集成 worker 负责审查、验证和最终提交；P2–P6 期间的路线切换由协调者串行完成并在各包记录，P7 最终审查。pages 用已有 runs 上下文创建 Agent，会缺必要信息才补读；按钮只发意图，agents/runs 互不导入。

核对所有原 URL/query、命名导航、懒加载、404、collector-demo 重定向。删除未引用的两个旧 Demo、旧 View/API/types/composables/domain 出口和零消费者文件，不能留下旧目录中第二实现或永久 compatibility flag。README 说明真实结构、依赖规则、运行/测试入口。

## 验证顺序与证据

按完整单测→typecheck/format/边界→build→Playwright/真实浏览器执行。架构检查覆盖 shared/module/page/app 方向、workflows→resources 唯一例外、跨模块仅 public、model 纯度、SFC 无具体 API/HTTP/EventSource、无 cycles，检查动态/type-only/相对 import。应用普通 HTTP 不留直接 fetch；原始 SSE 协议 E2E 探针与 Playwright route.fetch 明确标注例外。

真实浏览器跑资源→工作流→运行→报告→Agent；固定报告版本、各区失败、Agent 路由输入隔离/停止/分支/文件冲突、375px/44px 触控与长会话输入可见。服务启动不是烟测证据；必须记录实际页面动作和结果。对照 P0 用同构建/数据/路由环境比较入口 chunk、首屏请求和长会话交互，不报告没有测量支持的百分比。

每项失败记录 P0 是否已有及此次影响，不用 broad catch/默认假数据/跳过测试修饰结果。扫描最终 diff 的重复规则、吞错、隐式 fallback、过度 gate、未声明行为变化与本任务提交边界；逐个检查本任务 commit 的路径/diff 排除后端和其他任务文件，不核验整个共享工作区 hash 不变。OpenSpec 文档校验不替代行为验证，其他活动 change 不顺便归档。

## 提交与回退

仅唯一获授权的集成 worker 执行正常 commit/post-commit 自动推送，精确纳入本 change 与前端变动，普通实施 worker 禁止 commit；每次提交都审查暂存路径和 diff，排除并行后端及其他任务。按包记录完整 commit 链和依赖；回退底层时必须处理依赖其 API 的下游提交，不可只还原 shared 保留调用方。本任务不改变后端持久化或并行后端工作，回退单位为可独立验证的前端批次；回退也不得还原其他任务修改。

## 最终结果

### 2026-09-26 最终复验

复验基于 `refactor/frontend-architecture`，HEAD 为 `e134b15`；本任务提交链为 `a2f738d`、`5ef4242`、`e134b15`。开始复验时共享工作区已有后端、其他 OpenSpec 任务及前端文件的脏改动；复验未改动这些文件。下面只记录本轮实际执行的命令与结果。

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `npm test`（`frontend/`） | 0 | 45 files、207 tests 全部通过。包含 Agent A→B→A 输入隔离/离开清理和 `collector-demo` query 保留重定向的单元路由用例。 |
| `npm run typecheck`（`frontend/`） | 0 | `vue-tsc --noEmit` 通过。 |
| `npm run format:check`（`frontend/`） | 1 | 唯一报告 `scripts/check-architecture.mjs` 格式不符合 Prettier。该文件未在本轮修改。 |
| `npm run architecture:check`（`frontend/`） | 0 | 207 files 架构规则通过；27 files fixture 正反例通过。输出仍标明 legacy consumers 将在 P2–P7 到期，属于需继续核对的旧出口风险。 |
| `npm run build`（`frontend/`） | 0 | 3756 modules 构建成功。入口 `index-CzatgCpD.js` 为 293.62 kB；Agent `AgentPage-Fw_Qh2R8.js` 独立 chunk 为 83.48 kB。 |
| `npm run test:e2e -- --config playwright.agent-ui.config.ts`（`frontend/`，构建产物由 `vite preview` 提供） | 1 | Chromium 实际执行 7 项，1 passed、6 failed。通过项为“窄屏仍能打开全局设置”。失败项见下文。 |

Agent UI E2E 的六项失败为：重载后找不到“新建会话”按钮（60 秒超时）；初次进入 `/agents` 找不到同一按钮；长会话找不到预期的“第 20 条用户消息”；Workflow 续接未观察到预期的 `POST /agents/sessions`；运行中补充未观察到 fixture 预期的 `POST /agents/commands`；编辑分支发送预期 HTTP 503，却收到 HTTP 501 `POST /api/channels/web/commands`。最后一项确认了浏览器与 `agent-ui.spec.ts` 中 `installApi` fixture 的 API 契约不匹配：fixture 未处理页面实际请求的 `/api/channels/web/commands`，兜底返回 501。其他失败按实际断言保留，未推断为同一根因，也未修改 fixture 或业务代码。

真实浏览器尝试使用 Tabbit 打开 `http://localhost:3000/agents`。页面导航到目标 URL 后，首次脚本在读取标题时收到 `Target page, context or browser has been closed`；按恢复流程读取 receipt/diagnose 和标签库存后，重连返回 `CLAIM_FAILED`、`codeDispatched:false`。因此 Tabbit 未提供后续页面操作结果。本地 Chromium E2E 已实际打开 Agent 页面、操作全局设置并执行窄屏用例，但 Agent 页面其余 E2E 失败后即停止；375px 长会话断言未完成。resources→workflows→runs→report→agent 的完整浏览器导航、浏览器级 A→B→A/离开清理及 `collector-demo` 重定向本轮未完成；对应路由单元测试通过，不能替代真实浏览器证据。

本轮结果不全绿，未勾选未通过项，也未进行第三轮修复。待处理证据为 `scripts/check-architecture.mjs` 格式检查及 Agent E2E fixture/API 路径契约差异；在浏览器级复验成功前，以上场景仍属于未验收。

### 2026-09-26 Agent Web 命令 fixture 复验

本轮仅修复前端验证层与证据：`scripts/check-architecture.mjs` 按 Prettier 规范化；`agent-ui.spec.ts` fixture 按真实 `POST /api/channels/web/commands` envelope 分派 new/workflow/message/append/fork/stop，维护 session 状态和带 `id`/`data` 的 `/api/channels/web/sessions/:id/events` SSE 回放；历史 `message.completed` 样本补齐协议要求的 `incremental` 字段。`agent-live-ui.spec.ts` 的真实探针同步使用 Web channel SSE/stop command 路径。未修改后端。

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `npm run test:e2e -- --config playwright.agent-ui.config.ts --grep '正式 Agent\|未设置默认模型\|长会话'` | 0 | 3/3 targeted passed。 |
| `npm run test:e2e -- --config playwright.agent-ui.config.ts` | 0 | 7/7 Agent UI tests passed。 |
| `npm test` | 0 | 45 files、207 tests passed。 |
| `npm run typecheck` | 0 | `vue-tsc --noEmit` passed。 |
| `npm run format:check` | 0 | Prettier 全部通过。 |
| `npm run architecture:check` | 0 | 207 files 与 27 fixtures 通过。 |
| `npm run build` | 0 | 3756 modules 构建成功。 |

本轮未运行真实后端会话或 Tabbit 浏览器复验；真实浏览器限制与完整跨模块导航缺口仍按上节记录，未将其标记为通过。
