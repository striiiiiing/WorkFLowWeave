# Agent 演示交互落地正式页面

## 范围与依据

- 用户授权：以 `/agent-demo` 的界面实现正式 `/agents`，仅改前端、接入已有 API，使用资源配置中心的供应商渠道，完成后 commit。
- 依据 `../../design.md` §3、§8–10 与 `../../frontend.md` §1–7；不改 proposal/design。现有演示布局已进入正式组件，本轮补齐交互与契约，属于跨组件状态同步修复。
- 模型唯一来源为已有 `/agents/models` 和 `/agents/config.models`：`AgentService.model_views()` 从 ResourceStore 的 `ai` 资源投影 `reference/ai/provider/model`。前端原样提交 reference，按供应商渠道分组，不另读凭据、不硬编码模型或创建供应商配置。
- 无会话时先创建并选择渠道模型；已有会话切换只影响下一轮。摘要沿用已配置 AI 资源，空值语义按现有 API 保留。
- 用户追加要求默认模型与按渠道排序：`AgentConfig` 没有可写的默认模型字段（`src/logagent/agent/config.py`）；保持纯前端范围，将唯一默认引用保存为浏览器 localStorage `logagent.agent.default-model`，UI 明确仅当前浏览器有效。不保存凭据，不把该字段塞入服务端配置。新建和 Workflow 续接预选默认引用，已删除的引用显式报错；既有会话模型不覆盖。
- 所有模型选择入口共用渠道/模型排序函数，使用中文 locale 和 numeric 排序，保证相同渠道聚集、同名模型保留完整资源引用。用户要求不再指向 demo，移除 Agent demo 导航、正式页面链接及路由，暂留文件供用户后续删除。
- 命令与普通消息使用已有 command 信封；停止使用独立 cancel 动作。菜单仅匹配命令词，带参数指令交给提交逻辑。输入法组合期间不发送。
- 不猜测上下文容量、工具执行类别或沙箱能力；加载/失败明确展示。设置工具切换不覆盖未保存配置草稿。

## 实施与验证

- [x] 模型选择、新建/Workflow 续接、资源中心入口。
- [x] 命令菜单、运行中追加、独立停止、分支编辑失败后保留已创建分支。
- [x] Workflow 历史、设置反馈、预算与对话阅读体验、窄屏入口。
- [x] 定向测试 → 类型检查 → 构建 → 最小烟测 → 差异自审 → commit。

## 验收边界

- 已有未提交 AGENT.md 删除、CollectorDesignDemoView.vue 和 frontendFix 工作流报告任务记录不纳入本次提交。
- Tabbit 实际调用创建页面失败：`Target.createTarget: Task-scoped CDP command could not be dispatched`；diagnose/inventory 无可用页面，已 finish 释放任务。不能声称浏览器视觉验收通过。
- 用户后续明确要求独立浏览器 QA 和只读交互审查；结果记录于下文，组件测试不替代浏览器验收。
- 第一轮针对已有 Agent 组件的回归暴露旧测试仍定位已移除的按钮/样式；改为现有可访问入口，保留行为断言。第二轮发现运行态 EventSource mock 未触发 onopen、续接模型选择后未等待 DOM 按钮状态刷新，修正测试驱动后 7 个文件 / 32 项通过，包含新增默认模型、排序、排队、中文输入法、设置失败、工具切换保留草稿与分支发送重试用例。
- 会话草稿和未知发送 receipt 改为按会话保存，异步响应只能修改原会话草稿。测试抓到首次插入时直接返回原始对象造成输入无响应，改为始终从响应式字典读取；页面10项回归通过。
- 独立审查指出代理 HTTP 502/504 仍可能已经提交，现将 HTTP 5xx 与网络断连同样标记结果未知，保留请求 ID；读取浏览器默认模型的本地异常在请求分类之前处理，避免误报已发送。新增 gateway timeout 重试用例。
- 只读审查确认 `/workflow <id>` 创建会话的既有 API 不按 `request_id` 去重，因此前端未知结果时阻止原样重复提交并提示先查会话列表；用户改写指令才产生新请求。服务端会话创建完整幂等性超出“仅前端、沿用已有 API”范围，无法由前端实现保证。
- 用户明确授权资源中心的 `mock` 测试模型可随意调用，真实目录确认 `diagnose-provider-old:mock`；浏览器 QA 已获知，只使用该模型，不调用同渠道另一模型。
- 非写入 HTTP 烟测：`/agents`、`/api/agents/config`、`/api/agents/models`、`/api/agents/sessions` 均 200，目录实际含2个模型、会话列表7条（测试当时）。类型检查和首次构建通过；后续状态修复后还需最终验证。

- 最终暂存代码复制到独立 worktree `/tmp/logagent-agent-validation`，排除同时进行的 Collector 改动：7 个定向文件 / 34 项单测通过，`npm run typecheck` 通过，`npm run build` 通过（3583 modules）。共享工作区的 Collector 曾出现未使用变量/缺失属性错误，不修改或提交他人代码。

- 浏览器环境：Tabbit task-scoped CDP 不可用；QA 将缺失的 Chromium 动态库仅解压到 `/tmp/logagent-agent-ui-libs` 后运行真实 Playwright Chromium。初轮拦截 `**/api/**` 误伤 `/src/api/*.ts`，修为仅拦截 pathname 以 `/api/` 开头；按真实 Element Plus DOM 修正选择器与 Workflow fixture。5 项受控 API 的浏览器用例分别通过，覆盖默认持久化/排序/新建、Workflow 续接、追加与停止、分支发送失败重试、390px 设置入口。
- 最终新增“创建结果未知”回归后，composer 4 项、页面12项均通过；加其余既有定向用例共36项。真实后端首轮测试会话 `agent_669afcb32f27452ca95589e117943ff8` 使用获准 `mock` 完成首轮，子代理继续真实 UI 多轮/分支/停止验收。

- 最后提交版本在独立 worktree 再次 `npm run typecheck`、`npm run build` 全部通过。浏览器受控测试可复现命令：`cd frontend && npx playwright test --config playwright.agent-ui.config.ts`；本 WSL 缺系统库时加 `LD_LIBRARY_PATH=/tmp/logagent-agent-ui-libs/usr/lib/x86_64-linux-gnu`。
- LangChain 边界沿用 `../../frontend.md` 第1段：后端自定义 FastAPI SSE 不兼容 `@langchain/vue useStream`，本轮继续现有 `useAgentStream`，没有引入第二套 transport。
- 本次复验：Agent 定向单测 27 项、完整前端单测 133 项通过；`vue-tsc --noEmit` 与 Vite 生产构建通过（3581 modules）。受控 API 浏览器用例 5 项通过。
- 本次使用 `diagnose-provider-old:mock` 建立真实会话 `agent_f6d9ef133e5441eeb8e5011bccd536ab`，真实 SSE 完成连续回复（含 `read` 工具调用）、分支、模型菜单、文件/设置/Workflow/分支抽屉、追加、取消及 390px 窄屏检查。Tabbit Windows CLI 可诊断/结束任务，但当前实例没有可用窗口且创建页报 `Target.createTarget: Task-scoped CDP command could not be dispatched`；已改用本地 Chromium 对真实后端执行浏览器验证。
- 实时测试先后发现 URL 断言未等待分支路由变化，以及分支图按钮使用了不存在的 accessible name；按实际页面状态和 `AgentHeader` title 修正 QA 定位后通过。该两处为测试同步/定位问题，不是产品行为缺陷。
- 按用户指出的分支 `branch_fcedfd7c3bde458bb9340eae171f2719` 从 `/agents` 会话列表进入对应会话 `agent_345a602b203d46f2aa1bf24a34d1ef6f`，其模型为 `diagnose-provider-old:mock`、Workflow 绑定、状态 `completed` 且可续接。在当前工作树真实浏览器发送“你好”，请求返回 202，SSE 终态为 `completed`，页面显示“你好！😊有什么我可以帮你的吗？”，无前端异常或失败请求；该用户报告的问题在本次验证中未复现，因此不将其记作已修复。
