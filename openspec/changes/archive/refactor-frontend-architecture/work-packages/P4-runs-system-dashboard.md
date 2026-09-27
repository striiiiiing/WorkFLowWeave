# P4 运行、系统与首页

根任务：[tasks.md §5](../tasks.md#5-p4--运行系统与首页闭环)。依赖 P1，独立于 P2/P3/P5/P6。依据：[原设计](../../design-frontend-architecture/design.md) §3.3、§3.4、§4、§5、§9。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/LogAgent` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。新 worker 统一使用 GPT-6 Astra medium，只改获分配文件，禁止切 branch、stash、reset。普通实施 worker 禁止 commit；唯一获授权的集成 worker 串行处理公共文件、审查验证并精确提交，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 自动推送钩子，禁止 SKIP_WORKFLOW_PUSH 或覆盖 hooksPath。主代理仅编排和传递交接信息，不执行代码检查或验证。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 文件所有权

写 `modules/runs/**`、`modules/system/**`、`pages/runs/**`、`pages/plugins/**`、`pages/dashboard/**` 及相应测试；迁移旧 RunsView/RunDetailView/PluginsView/DashboardView、report UI、SessionTable/StatusBadge、useSession、domain/session/report/pluginHealth/capabilities。P1 的 system 能力查询与 workflows 列表公开契约需保持稳定，P2/P3 在消费它们。

## 交接与职责

runs 提供列表/详情/阶段控制器、触发/取消/恢复操作和已加载只读运行上下文；报告身份固定 `(session_id, version, stage)`。UI 接受报告解析结果，不自行请求，不 import router；恢复资格来自后端。轮询 2000ms 从前次请求结束计时，终态/错误停止。

system 拥有 plugins/health 独立查询、诊断投影与 reload。Dashboard 按指定组件树组合：Page、Metrics/MetricCard、RecentRunsPanel/SessionTable、SystemHealthAlert/PluginHealthPanel/ComponentHealthPanel。useDashboard 只组合 workflows/runs/system 公开控制器；health 一份结果用于三个消费者，运行列表 limit 5，读取时间随接纳响应更新。

## 验收与提交

报告版本改变清旧正文、局部 artifact 失败、分页筛选提交、轮询不重叠、取消/恢复与未知写入结果；首页任意一项失败不遮挡其余结果且不显示错误零值，统一刷新不引入全页单一成功态。系统健康合法 503 与 error 信封分别测试。

建议 runs 和 system/dashboard 分为两个可运行提交；前者交接 P7 已加载上下文与续接按钮意图，后者交接首页所有区块。按每闭环单测→type/边界→build→真实浏览器验证后由协调者切换旧路由；不要在 runs 实现 Agent 请求。

## 实施证据

### 实施决策与公开合同（2026-09-25）

结构性提取依据原设计 §3.3/§3.4/§5：查询和写动作归唯一控制器，纯模型迁移后删除旧实现；页面仅处理路由与组件装配。本包按一个运行/系统/首页闭环验收提交，避免 runs 的 SessionTable 迁移后保留旧首页导航实现。

- `runs/public` 新增 `useRunList(api?: Pick<RunsApi, 'list'>)`、`useRecentRuns(api?)`、`useSession(id, api?: Pick<RunsApi, 'get'>)`、`usePhaseReport(identity, api?: Pick<RunsApi, 'phase'>)`、`useRunDetail(id, api?: Pick<RunsApi, 'get' | 'phase' | 'recovery' | 'recover' | 'cancel'>)`。默认 API 均来自 P1 的注入 key；不存在业务层具体 transport 导入。
- 列表每页 20、首页 5、轮询 2000ms 延续被替代 `RunsView`/`DashboardView`/`useSession` 的既有默认值，原设计 §5 要求保留行为；筛选草稿只在提交时成为查询身份，datetime-local 在提交边界转 ISO instant。轮询在响应完成后计时，终态、失败、销毁停止。
- 报告身份固定为 session/version/stage；`useQuery` 承担取消、代次、销毁和清旧数据，`usePhaseReport` 使用唯一 `parsePhase`，解析失败显式成为该阶段错误。版本更新自动触发一次每阶段/恢复资格读取；同版本手动刷新才主动刷新这些子查询，避免重复读。
- `useRunActions.trigger/cancel` 冻结签名不变；抽出唯一 `useCancelAction` 供详情依赖最小 API，并新增 `useRecoveryAction` 复用既有 failure/unknown 分类，无写入重试。详情用明确“取消/恢复结果未知”展示不确定写入，不用恢复或取消 HTTP 成功冒充最终会话状态。
- `useRunDetail.loadedContext` 为已加载 session 与阶段状态的只读投影，无额外 get/list；`RunActions` 发继续意图，`RunDetailPage` 转发上下文。**P7 过渡**：`views/RunDetailView.vue` 仅保留约十行 route composition，把现有 AgentContinueButton 放进 continuation slot；不再有运行查询/草稿/动作实现。P7 需接管完整续接并删除此壳；本包不声称完整续接已验收。
- `system/public` 提供 `useSystemHealth`、`useSystemDiagnostics`、`usePluginReload` 和纯 `pluginHealthRows`；合法 health503/信封继续使用 P1 的唯一 transport 校验。plugins 与 health 分别失败/刷新；诊断格式错误只影响诊断投影，不使其他首页区域渲染失败。reload 的传输失败与成功响应中的 discovery errors 分别展示，保留完整错误报告。
- `useDashboard` 仅组合 workflows/runs/system 公开控制器。真实组件树包含 DashboardMetrics/MetricCard、RecentRunsPanel/SessionTable、SystemHealthAlert、PluginHealthPanel、ComponentHealthPanel；health 查询一份传给各消费者。数量在尚未成功读取时显示“—”，同身份刷新失败保留上次成功值和 readAt。
- 删除旧 RunsView/DashboardView/PluginsView，旧 report UI/SessionTable/StatusBadge/useSession，以及 domain/session/report/pluginHealth 和无消费者的 capabilities 过渡出口；保留的唯一实现归 modules。

### 验证进度

已完成：runs 原相关 5 文件 24 测试；新增详情 3 测试；system/详情/动作/首页/shared JSON 回归 5 文件 31 测试；全量前端单测 40 个文件、193 项通过；`npm run typecheck`、`npm run format:check`、架构检查（实际源码及 27 个正反例）和 `npm run build` 通过。构建产物中首页入口约 432 KB，运行详情、报告、工作流编辑器和资源编辑器保持为独立路由 chunk，未再把编辑器/报告静态带入首页入口。全量单测曾发现 P2 遗留 provider-view 测试缺少新注入，已由对应改动补齐，未掩盖失败。

集成浏览器验收：`npm run test:e2e` 已启动临时后端和 preview，但 Chromium 在进程启动前因宿主缺少 `libnspr4.so` 退出，10 个用例均未执行到应用断言；Tabbit 也成功加载 preview 响应（HTTP 200）后因本地浏览器运行时关闭页面，未形成可归因于应用的断言结果。因此本次提交保留自动化浏览器阻断证据，不把它描述为通过；安装该系统库后应重跑 `npm run test:e2e`，重点覆盖首页局部失败、运行筛选/详情、插件诊断和 375px 布局。

提交范围：本提交只包含前端 P4 页面、runs/system 模块、相关测试、路由/Playwright 配置和本任务记录；工作区中后端双向 channel 及其他 OpenSpec change 的修改未暂存、未提交。

### 宿主依赖安装后复验（2026-09-26）

用户安装 Chromium 所需 Ubuntu 库后，`ldd` 不再报告缺失依赖，Playwright 可以启动真实 Chromium。首次完整 E2E 为 7/10：运行记录测试仍按迁移前的 `router-link` 查找链接并超时；该超时留下的测试数据使后续工作流用例出现两个“编辑”按钮；跨窗口模型目录用例依赖 headless `bringToFront()` 自动派发 `focus`，导致等待 `/api/ai` GET 超时。前端 E2E 随现有 UI 合同改为点击 SessionTable 的按钮，并在返回编辑页后显式派发 `focus` 事件。两个失败用例独立复验 2/2 通过；完整 `npm run test:e2e` 最终 10/10 通过（约 1.1 分钟），覆盖临时真实后端、运行/工作流/资源/报告/监控和 375px 布局。测试修改未改变产品代码或后端。
