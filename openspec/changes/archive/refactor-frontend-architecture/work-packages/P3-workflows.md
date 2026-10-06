# P3 工作流闭环

根任务：[tasks.md §4](../tasks.md#4-p3--工作流闭环)。依赖 P2 已冻结的资源编辑器/gateway；可与 P4/P6 并行。依据：[原设计](../../design-frontend-architecture/design.md) §3.4、§5.3、§6。

## 当前执行约束（用户审核后更新）

本包只在 `/mnt/d/code/WorkFLowWeave` 内就地执行，按根 tasks 的文件所有权与其他 worker 并发；不新建或使用其他工作目录/worktree。新 worker 统一使用 GPT-6 Astra medium，只改获分配文件，禁止切 branch、stash、reset。普通实施 worker 禁止 commit；唯一获授权的集成 worker 串行处理公共文件、审查验证并精确提交，逐个 commit 排除后端及其他任务文件，沿用现有 post-commit 自动推送钩子，禁止 SKIP_WORKFLOW_PUSH 或覆盖 hooksPath。主代理仅编排和传递交接信息，不执行代码检查或验证。后端双向 channel 正在另一任务中演进；本包仅记录真实契约测试当时的 HEAD/dirty 与协议差异，不要求其全局不变，不干预或静默兼容不匹配的后端。前端针对性测试可独立继续。

## 文件所有权与边界

写 `modules/workflows/**`、`pages/workflows/**`、工作流 unit 测试；迁移/删除旧 WorkflowsView/WorkflowEditView、components/workflow、domain/workflow 和遗留工作流 type 出口。P1 列表控制器、使用位置 API 和 runs 最小 trigger/cancel 页面动作控制器（含实现）已供本包消费，保持公开签名或先与消费者协商；P4 后续只在该契约上接入完整运行控制器。不得编辑 resources 内部或 app 路由公共文件。

useWorkflowEditor 唯一拥有 sources/analyses/fan_in/channels/overrides 草稿。基本信息、阶段导航、来源/分析/汇聚/通知独立 SFC；SourceStepCard 继续分为来源选择/绑定列表/绑定项/配置编辑。子组件只读切片并发命名动作，不直接改嵌套 props，不双向 watch 同步整份草稿。

来源异步操作协调者调用 P2 gateway 和草稿动作；它不能另存完整工作流。脱离必须调用后端 resolve，前端不复制模板/覆盖合并规则；共享写入成功后精确 refresh，独立保存只改当前草稿。恢复共享/发布保持原确认行为，资源成功与工作流未保存分别显示。

## 验收与提交

覆盖阶段往返、任务 ID 中间输入/合法唯一改名引用更新、汇聚关闭保留编辑值且提交按 null 语义、目录刷新保留草稿、窗口返回监听清理、过期请求、停用绑定/稀疏覆盖/显式空值。列表运行操作调用 P1 已实现并冻结的 runs 公共动作能力，由页面装配；P3 不导入 runs 内部，不依赖 P4 才能运行；P4 在保持已冻结契约的基础上扩展能力。

提交可拆草稿纯逻辑与编辑闭环两批，任何批次保持旧/新路由只有一个实际实现。最终按单测→type/边界→build→新增/共享/独立/保存回读的真实浏览器闭环提交，记录与 P2 契约一致的证据。

## 实施证据

### 2026-09-25 实施批次

依据原设计 §5.3 与 §6，工作流草稿的唯一拥有者为 `useWorkflowEditor`；`model/actions.ts` 以不可变返回值实现来源顺序、来源覆盖、分析任务改名/引用同步、汇聚 disabledDraft、通知覆盖和备份字段更新。工作流默认值沿用 `src/workflowweave/models.py` 对应 DTO（并与原 `domain/workflow.ts` 一致）：采集/分析并发均为 4、来源输入分隔符为两个换行、备份默认启用且四类快照均启用；这些值是后端模型和历史行为依据，不新增前端隐式默认层。

`useWorkflowEditor` 在路由身份变化时清空旧实体并只接受相同 ID 的服务器快照；同身份刷新、目录刷新和迟到响应保留未保存草稿。来源脱离/发布通过 P2 `SourceConfigEditorGateway`，`workflow-draft` 只调用 `applySource`，`shared-resource` 才写资源 API；resolve 响应会校验工作流代际，切换工作流后拒绝旧响应。来源使用位置继续由 `sourceUsage`/`useSourceUsage` 投影，当前草稿按 ID 替换服务端快照。

新增页面与区块位于 `modules/workflows/ui/**`、`pages/workflows/**`；列表通过 P1 `useRunActions.trigger` 发起运行并导航 `/runs/<session_id>`，不导入 P4 内部实现。`app/router.ts` 未修改，旧路由仍指向遗留 View，实际路由切换、旧 View/组件删除留给 P7 集成 worker；本批次没有声明浏览器路由烟测完成。

提交链：`4153a08`（草稿模型、动作、编辑器控制器及 5 项控制器测试）；`db1880b`（工作流页面、来源/分析/汇聚/通知/备份 UI）；`a9933e2`（UI 回归测试、旧 domain 过渡别名和本证据）；`8500b51`（新增来源目标选择修复）。已验证：完整前端 Vitest 37 文件/186 项通过；P3 定向 2 文件/8 项通过；`vue-tsc --noEmit`、Prettier、架构检查（177 文件及 27 fixtures）、production build 和 `git diff --check` 通过。未执行真实浏览器流程，因 router 集成按 P7 冻结。

### 2026-09-26 最终收口

最终 P3 提交链：`4153a08`（草稿模型与编辑器控制器）；`db1880b`（工作流页面及区块）；`a9933e2`（UI 回归与实施证据）；`8500b51`（按资源目录选择新建/替换目标）；`2431387`（整理 P3 验收证据）；`bd6da70`（避免发布来源后重复刷新使用位置）；`cc914cd`（恢复来源确认、保护已删除资源对应的独立覆盖，并拆分 `WorkflowBasicInfo`、`WorkflowStageNav`、`SourceSelector`、`SourceBindingList`、`SourceBindingItem`）。本次最终验证记录为：工作流定向测试 3 文件/9 项通过，来源确认测试 2 项通过，完整前端 Vitest 37 文件/186 项通过；`vue-tsc --noEmit`、架构检查及 fixtures、Prettier、`git diff --check` 和 production build 均通过。上述 P3 提交只包含工作流实现、测试和本工作包证据，不包含 router、P4、backend 或 resources 改动。

`app/router.ts` 仍将工作流 URL 指向旧 View，因此新工作流页面尚未接入实际路由；未执行真实浏览器流程。本包把路由切换、旧 View/组件清理及真实浏览器验证留给 P7，不能据此宣称工作流的端到端浏览器验收完成。
