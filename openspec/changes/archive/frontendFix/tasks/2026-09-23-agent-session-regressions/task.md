# Agent 会话布局与事件回归

## 需求与依据

- 用户复现 `branch_fcedfd7c3bde458bb9340eae171f2719` 的长内容将输入框顶出视口；用户明确要求纯前端修正，并指出输入框应固定在会话底部。
- 用户询问 `turn.resources`、`turn.completed` 的含义，以及每次新建会话重复确认的原因。
- `../../../add-file-centric-agent/frontend.md` §1 将页面定义为会话列表、聊天区和窄屏布局；§2 规定输入区为聊天区组成部分；§7 要求验证窄屏布局。
- `../../../add-file-centric-agent/design.md` §9.1 定义每轮固定资源快照与 `completed` 轮次状态；§10 将 `turn.completed` 列为终态事件。前端 `useAgentStream` 已消费 `turn.resources` 更新 `active_resources`，不应再把原始类型名作为聊天文本。
- 不修改 proposal.md、design.md、后端 API 或事件契约。

## 根因与实现决策

- `.transcript-viewport` 已是消息唯一滚动区，`.composer-container` 使用 `flex: 0 0 auto`；但 `.agent-view-shell` 原高度为 `100vh - 84px`，没有扣除布局中 56px 顶栏与页面内容区上下留白。页面因此自身产生纵向滚动，滚动页面时才看得到输入器。
- 桌面高度依据：视口高度减 56px 顶栏及 `page-content` 上下各 32px 留白，即 `100dvh - 120px`；兼容无动态视口单位的浏览器保留 `100vh` 声明。
- 窄屏 `page-content` 上下留白为 16px，故高度采用 `100dvh - 88px`。保持输入器在聊天 flex 列底部，历史内容只在 transcript 内滚动，不使用 fixed 定位覆盖消息或遮挡输入器。
- `turn.resources` 是本轮模型/工具代次资源快照，只用于会话状态；从对话 transcript 隐藏。`turn.completed` 表示当前轮成功终止而非会话不可继续，继续显示本地化完成状态。
- 点击“新会话”是显式创建动作。有效的浏览器默认模型应直接创建；没有默认模型时才显示模型选择步骤，保留用户首次配置选择的路径。创建失败继续显示错误，不做静默成功。

## 验证

- [x] Agent transcript、stream 与创建流程定向单测：22 项通过。
- [x] Agent UI Playwright：7 项通过；桌面与 375px 窄屏长历史下仅 transcript 滚动，输入器保持在聊天区底部；默认模型直接创建，无默认模型仍可选择。
- [x] 运行中的 mock 服务浏览器实测：引用分支可发送“你好”并呈现回复；新会话无确认即可创建、发送并在重载后恢复回复。1440x900 与 375x812 均无文档滚动，composer 在 transcript 滚动前后位置不变。
- [x] 定向 Prettier 检查、`git diff --check` 与 Vite 生产构建通过。
- [ ] 本轮 Playwright 重跑未能启动 Chromium：环境缺少 `libnspr4.so`；先前 Agent UI Playwright 的 7 项通过记录和真实会话浏览器实测仍保留。
- [ ] `vue-tsc --noEmit` 被工作区已有的 `CollectorDesignDemoView.vue` 类型错误阻塞（非 Agent 文件）。
- [ ] 隔离 Agent 后端 E2E 夹具未通过：其 `SmokeLifecycle` 未装配当前工作区新增的 `agent_channel`，页面明确报“Agent 双向渠道尚未装配”；这是后端夹具契约问题，本次不修改后端。
- [ ] 按要求通过 Windows PowerShell 调用 Tabbit；目标页创建失败（`Target.createTarget: Task-scoped CDP command could not be dispatched`）。只读诊断确认任务下没有标签，`finish` 正常完成；未操作其他任务。Tabbit 不作为本轮通过证据。
