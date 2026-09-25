# P6 Agent 控制器与 UI

根任务：[tasks.md §7](../tasks.md#7-p6--agent-控制器ui-与稳定会话作用域)。依赖 P5；与 P3/P4 可并行。依据：[原设计](../../design-frontend-architecture/design.md) §3.4、§5.1、§5.2、§7。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/LogAgent` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。新 worker 统一使用 GPT-6 Astra medium，只改获分配文件，禁止切 branch、stash、reset。普通实施 worker 禁止 commit；唯一获授权的集成 worker 串行处理公共文件、审查验证并精确提交，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 自动推送钩子，禁止 SKIP_WORKFLOW_PUSH 或覆盖 hooksPath。主代理仅编排和传递交接信息，不执行代码检查或验证。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 文件所有权与集成

写 `modules/agents/composables/` 的 commands/files/其他控制器（复用 P5 已提取的 useAgentSession）、`modules/agents/ui/**`、`pages/agents/**` 和 Agent 控制器/组件测试，迁移旧 AgentsView、components/agent（续接跨模块部分留 P7）与遗留 useAgentStream 适配。不改变 P5 API/model 公共签名而不通知；路由 key/App 装配变更由 GPT-6 Astra medium 集成 worker 按协调者安排串行应用。

session 生命周期直接复用 P5 的注入式 useAgentSession；页面只协调选中会话，不能重写历史/快照/SSE 顺序、generation 或第二 reducer。commands 在稳定 Agent 页面作用域按 session 保留输入/待确认请求，回执仅写对应会话；files 控制器拥有路径/分页/内容/ETag/冲突。send 与 stop 独立状态；未知结果保留原 ID/payload，内容变更新 ID；不自动重放操作。

页面仅协调 route/选中会话/组件布局。拆出侧栏、Header、Transcript/消息项/ToolCall、Composer/SlashMenu、BranchDrawer、FileDrawer、设置、新建/分支表单，键盘/光标/菜单留 Composer。不得旧脚本整体搬 usePage，不新增巨型 AgentContent。

## 验收与提交

配置查询同屏唯一，设置只创建编辑草稿并在保存后刷新同一查询。文件冲突保留本地内容，默认模型缺失显式展示。测试 session A→B→A、A 回执晚到 B、stop 不受 send pending 阻塞、断线恢复、旧终态、新内容新请求、分支、文件冲突与配置请求次数。

真实 App/router 验证 `/agents` 与 `/agents/:sessionId` 使用同一个稳定 Page key，离开 Agent 后释放作用域；不能只 mount AgentPage 后声称路由保持通过。按单测→type/边界→build→真实路由/长消息/375px 浏览器检查提交，再移除旧页面/适配。

## 实施证据

2026-09-26 P6 实施记录：

- 控制器职责：`modules/agents/composables/useAgentCommands.ts` 按 session ID 保存输入、原始 payload/request ID、未知回执与可重试状态；`send` 与 `stop` 使用独立 pending/error。`useAgentFiles.ts` 拥有路径、分页、全文读取、草稿、hash/If-Match、If-None-Match 与 409 冲突保留。`useAgentBranches.ts` 保留 fork 后重试发送的 request ID；`useAgentSettings.ts` 由页面创建单一 config query，设置弹窗只编辑草稿，保存/工具切换刷新同一查询。
- UI 所有权：`pages/agents/AgentPage.vue` 只组合路由、选择会话和视图；侧栏、Header、Transcript、消息工具项、Composer/SlashMenu、分支/文件/设置/创建/编辑表单位于 `modules/agents/ui/**`。旧 `components/agent` 仅保留迁移兼容壳，页面不再导入 `views/AgentsView.vue` 或 `useAgentStream`。
- 路由语义：`app/router.ts` 的 `/agents` 与 `/agents/:sessionId` 共用同一异步页面工厂；`app/App.vue` 对 Agent 使用稳定 key。`tests/unit/agent-app-route.test.ts` 通过真实 App/router records 验证 A→B→A 选择与离开 Agent 后输入清理，配置查询仅一次。控制器单测覆盖 A→B→A 迟到回执、同 ID 明确重试、内容变更新 ID、独立 stop、未知 workflow 不重试和文件 ETag 冲突。
- 验证：`npm test -- --run tests/unit/agent-controllers.test.ts tests/unit/agent-composer.test.ts tests/unit/agent-components.test.ts tests/unit/agent-settings-modal.test.ts tests/unit/agent-view.test.ts tests/unit/agent-app-route.test.ts`，6 文件/31 项通过；`npm run typecheck`、`npm run architecture:check`、`npm run build` 通过。`npm run format:check` 在格式化前曾失败，随后对本包文件执行 Prettier；最终格式检查需由 P7 全量复跑。Build 输出 AgentPage 独立约 82 KB chunk，未再静态导入编辑器/报告页面。
- 浏览器交接：尚未在本代理运行浏览器。后续 Luna 必须用真实 App 路由检查 A→B→A 草稿隔离、离开清理、停止独立于 send、分支与文件 409 冲突、设置单次配置读取，以及桌面/375px 长消息输入器可见性。
- 提交链：中途控制器提交为 `refactor(frontend): isolate agent command and file state`；P6 最终提交将精确包含本包前端/UI/测试、必要 `app/App.vue`/`app/router.ts` 和本记录，不包含后端及其他并发任务脏文件。
