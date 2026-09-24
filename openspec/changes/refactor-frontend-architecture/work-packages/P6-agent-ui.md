# P6 Agent 控制器与 UI

根任务：[tasks.md §7](../tasks.md#7-p6--agent-控制器ui-与稳定会话作用域)。依赖 P5；与 P3/P4 可并行。依据：[原设计](../../design-frontend-architecture/design.md) §3.4、§5.1、§5.2、§7。

## 文件所有权与集成

写 `modules/agents/composables/` 的 commands/files/其他控制器（复用 P5 已提取的 useAgentSession）、`modules/agents/ui/**`、`pages/agents/**` 和 Agent 控制器/组件测试，迁移旧 AgentsView、components/agent（续接跨模块部分留 P7）与遗留 useAgentStream 适配。不改变 P5 API/model 公共签名而不通知；路由 key/App 装配变更由 GPT-6 Astra xhigh 集成 worker 按协调者安排串行应用。

session 生命周期直接复用 P5 的注入式 useAgentSession；页面只协调选中会话，不能重写历史/快照/SSE 顺序、generation 或第二 reducer。commands 在稳定 Agent 页面作用域按 session 保留输入/待确认请求，回执仅写对应会话；files 控制器拥有路径/分页/内容/ETag/冲突。send 与 stop 独立状态；未知结果保留原 ID/payload，内容变更新 ID；不自动重放操作。

页面仅协调 route/选中会话/组件布局。拆出侧栏、Header、Transcript/消息项/ToolCall、Composer/SlashMenu、BranchDrawer、FileDrawer、设置、新建/分支表单，键盘/光标/菜单留 Composer。不得旧脚本整体搬 usePage，不新增巨型 AgentContent。

## 验收与提交

配置查询同屏唯一，设置只创建编辑草稿并在保存后刷新同一查询。文件冲突保留本地内容，默认模型缺失显式展示。测试 session A→B→A、A 回执晚到 B、stop 不受 send pending 阻塞、断线恢复、旧终态、新内容新请求、分支、文件冲突与配置请求次数。

真实 App/router 验证 `/agents` 与 `/agents/:sessionId` 使用同一个稳定 Page key，离开 Agent 后释放作用域；不能只 mount AgentPage 后声称路由保持通过。按单测→type/边界→build→真实路由/长消息/375px 浏览器检查提交，再移除旧页面/适配。

## 实施证据

待填控制器职责与导出、状态竞争测试、真实路由/窄屏记录、commit 与删除清单。
