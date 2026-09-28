# Workflow 前后端实时联动任务

## 本轮范围与工作区

用户要求基于 `redesign-workflow` 建立新 worktree，先按 OpenSpec 修改文档，并强调前端 Workflow 应随执行及时更新。本轮完成规划文档，不将文档齐备记为运行能力已实现。

- worktree：`/mnt/d/code/LogAgent/.worktree/redesign-workflow`。
- 分支：`feat/redesign-workflow`，基线提交：`a1cf5e0`，来源分支：`refactor/frontend-architecture`。
- 主工作区的本变更尚未跟踪，已将 `redesign-workflow` 整个文档目录带入新 worktree；其他未提交代码、IDE 文件和归档迁移未带入。
- 源工作区已将历史 Workflow 设计移入 archive，但该移动尚未提交。新 worktree 使用基线中仍受 Git 跟踪的 `configurable-collection-analysis-workflow` 历史文件；仅把 proposal 与根 tasks 中该相对链接改回可解析位置，proposal 的目标和范围未改写。既有 design 所述“旧归档”是历史来源，不表示本分支已完成该目录迁移。
- 本轮补充 [design 第 4.1–4.3 节](../../design.md) 的前端执行视图、订阅同步与恢复交互，依据用户此次明确授权的前端适配要求；保留此前任务历史，新增本任务与根 tasks 第 7 节，不把历史设计记录改写成当前实现证据。

## 根因、影响范围与方案

这属于共享 API 契约与前后端状态同步的结构性修改。最小局部补丁是缩短轮询间隔或在阶段完成后刷新报告，但无法证明慢分支未结束时快分支结果已可见，还会重复查询阶段正文。因此选用既有设计的单次 astream → 已提交查询投影 → 只读订阅 → 前端逐项归并链路。

| 基线证据 | 实施影响 |
| --- | --- |
| `frontend/src/modules/runs/composables/useSession.ts` 的 `POLL_INTERVAL_MS = 2000` | 正常执行视图由订阅驱动；移除主路径定时轮询，保留主动刷新及必要状态同步 |
| `useRunDetail.ts`、`usePhaseReport.ts` 按 session/version/stage 读取阶段内容 | 新增逐项投影消费；只按确切结果引用读取需要的正文，不能每个事件刷新所有阶段 |
| `RunDetailPage.vue` 与 `RunProcessDetails.vue` 以最终报告和折叠过程为主 | 普通模式直接显示当前阶段与逐项状态；aggregate 可读不等待 notify，全局状态仍真实 |
| `frontend/src/pages/workflows/WorkflowListPage.vue` 触发成功后导航 `/runs/:session_id` | 保留该入口，真实验证导航后即可看到实时执行，不在配置页重复维护运行状态 |
| `src/logagent/interaction/routers.py` 没有 Workflow 事件路由 | 在本 change 增加只读订阅及 session 进度查询的必要字段；不能只修改前端假设接口已存在 |
| `src/logagent/interaction/channel_routers.py` 已提供 Agent SSE | 复用 HTTP/SSE 传输思路；Workflow 不复用 Agent 的 command、事件日志、游标重放或会话语义 |
| `runsApi.ts` 与 `RunActions.vue` 只有无参数 recover 动作 | 配合既有设计第 5 节，增加可用性核验和阶段选择，不以旧失败状态列表限制所有重跑 |

主要修改范围：`src/logagent/workflow/` 的流消费和查询投影，`interaction/routers.py`、`interaction/schemas.py`，以及 `frontend/src/modules/runs/`、`frontend/src/pages/runs/RunDetailPage.vue` 和 Workflow 触发入口的必要集成。前端传输通过 runs API 注入，页面消费模块公开接口，不直接依赖后端实现或 Agent 私有模块。实际新文件以消除重复职责为依据，不预建多层事件框架。

## 依据、取舍与默认值

| 决定 | 依据及理由 |
| --- | --- |
| 四类业务进度及必要错误状态 | [proposal](../../proposal.md)、[design 第 4 节](../../design.md)、[aggregate 补充任务](../2026-09-28-aggregate-progress/task.md)；逐项 fan-out、业务 fan-in、aggregate、output/channel 结果均及时可见，内部排序与 intent 不展示 |
| Workflow 独立只读 SSE 路由 | 数据从服务端单向推送，现有项目已有 HTTP/SSE 实践，无需新增 WebSocket 或独立消息平台；路径按现有 `/api/sessions/{session_id}` 资源边界扩展 |
| 连接就绪后查询并合并期间事件 | design 原有“重连查询补齐、不承诺持久化重放”要求；仅先 GET 再订阅会遗漏窗口中的结果，旧查询晚到还会回退界面 |
| 查询与事件共享已提交投影 | design 第 4、5.6 节的单一事实写入者；引用已提交业务版本，不把前端事件视作 checkpoint 完成，也不另存一份业务正文 |
| 轮次、业务版本、连接代次分别定位 | design 第 5 节已区分 execution_epoch 与业务 version；连接代次只过滤失效页面回调，不作为服务端业务身份或第二份执行状态 |
| 普通模式逐项可见，保持快照顺序 | 用户强调 Workflow 及时更新；原提案要求不等子图结束且稳定顺序，不能用修改后的配置解释正在运行的快照 |
| 两种恢复动作和再次发送说明 | design 第 5.2–5.4 节已确定无 stage 续跑、指定 stage 重做至 finish 和新轮次投递；前端必须准确表达这一已有行为变化 |
| 不新增延迟阈值与轮询默认 | 2000 ms 是旧实现事实，不是新方案默认；沿用“快分支在慢分支/arrange 完成前可见”的时序验收，不凭空承诺毫秒 SLA |
| 不照搬 Agent 心跳、重试或消息保留参数 | Workflow 没有持久化重放保证；实施需要传输重连/缓冲参数时须引用既有共享配置或补充实际依据，不能照抄 Agent 的轮询值或设无界缓存 |
| 并发、备份和保留期保持 | design 第 7 节已有默认值及依据，本轮前端补充不修改运行预算 |

## 文档任务

- [x] 1.1 建立并核对 worktree、分支和源目录文档副本，保留源工作区其他修改。
- [x] 1.2 按现有实现确认轮询、折叠报告、订阅路由缺失和旧恢复按钮的差距。
- [x] 1.3 补充 design、流式能力与恢复能力场景，并为三项新增能力补齐当前 OpenSpec 模板要求的 Purpose。
- [x] 1.4 严格校验 OpenSpec、检查 Markdown 链接/空白，审查文档 diff 并记录结果。

## 后端契约与前端实施任务

- [x] 2.1 统一 interaction schema 与 runs 类型，落实 session/epoch/业务身份、类别、状态/错误、摘要、结果引用/版本及正文可用性；字段说明更新在本记录中，不复制另一份主设计。
- [x] 2.2 扩展既有查询的当前逐项进度和轮次信息，保持指定历史版本读取不受新轮次污染；基于同一已提交事实发布结果通知。
- [x] 2.3 实现只读 Workflow SSE、就绪边界、必要终态通知及有界消费，证明订阅数量不改变业务调用次数；与根任务 2.3/2.5 共用同一执行与消费者。
- [x] 2.4 在 runs 模块实现可注入的订阅传输、首屏/重连同步和条目归并，替换运行详情固定轮询，处理旧快照晚到及同步期间结果到达的竞态。
- [x] 2.5 按 session/epoch/业务身份更新，按运行快照稳定排序；处理相同结果重复、fan-in/aggregate 去重、局部失败与不确定投递，避免依赖数组位置或 tags 定位。
- [x] 2.6 更新运行详情普通模式的进度、连接状态和报告可用性；aggregate 报告固定版本读取不等通知完成，不在每条事件后刷新全部正文。
- [x] 2.7 实现路由切换、作用域释放、终态核对、新轮次切换与失效回调隔离；断线仅停止观察，不取消后台运行。
- [x] 2.8 配合根任务 6.2 落实无 stage 续跑与阶段重跑的 API 参数、可用性和错误说明；新轮次由服务端确认，结果未知不得自动重发操作。

## 验证任务与验收依据

验证顺序：定向单元/契约测试 → 类型/静态检查 → 受影响包构建 → 真实集成与浏览器烟测。每条后端测试命令使用硬超时 60 秒；按测试文件拆分，不以取消超时换取“通过”。文档阶段不运行业务测试，也不提前勾选。

- [x] 3.1 后端以可控屏障阻塞慢来源/分析项，真实订阅快项结果；释放慢项前核对快项已提交且可查询。相同方式覆盖 aggregate 在 notify 前、确定回执在其他渠道前可见及内部事件过滤。
- [x] 3.2 契约/前端单元测试覆盖订阅就绪与查询竞态、快照晚到、重复乱序、断线期间终态、相同 session 新轮次与旧事件交错、备份关闭/过期正文和无通知目标。
- [ ] 3.3 基于 `frontend/tests/unit/run-detail.test.ts`、`runs-api.test.ts`、`runs-actions.test.ts`、`runs-view.test.ts` 及 Workflow 入口用例验证 API/状态/UI；阶段重跑覆盖已完成运行可重跑、再次发送说明、入口不可用及操作结果未知。
- [ ] 3.4 验证多页面订阅、重连不重复执行，页面切换释放连接与待处理任务，慢订阅者显式断开后可查询补齐，无静默轮询、无无界队列或遗漏终态。
- [x] 3.5 执行后端受影响静态检查和前端 `npm run typecheck`、`npm run architecture:check`；按实际修改执行相关构建，前端运行 `npm run build`。
- [ ] 3.6 浏览器从 Workflow 列表触发真实运行，保持慢分支屏障时观察普通模式快项已显示；验证 aggregate 报告与逐渠道结果、断网重连和阶段重跑至 finish。必须产生真实 HTTP/SSE 及浏览器交互证据，不能仅用 mock 事件或服务器启动代替。
- [x] 3.7 对照 design 与上述规范审查实现，检查单一事实来源、必要持久化、跨轮次隔离、订阅释放、没有隐藏降级或重复执行；运行 OpenSpec 严格校验后再汇总勾选根任务。

## 本轮验证记录

- `openspec validate redesign-workflow --strict --no-interactive`：通过，退出码 0。
- `openspec status --change redesign-workflow --json`：proposal/specs/design/tasks 文档齐备，退出码 0；仅表示规划完整，不表示运行能力实现。
- 10 份 Markdown 的本地相对链接、围栏配对、尾随空白和文件末尾换行检查通过。
- `git diff --check` 通过；本 change 已设为 intent-to-add，新增文件也纳入差异检查，未创建提交。
- 对照源工作区原始文档审查本轮增量；修改范围仅为本变更目录，前三份日期化详细任务按字节保持一致，实现任务未勾选。
- 文档差异审查完成：前端新增行为均对应 proposal 的实时进度目标及 design 既有恢复边界；查询补齐、轮次隔离和连接生命周期已分别有规范场景及实施验证任务。
- 本轮只修改文档，不运行前后端业务测试或构建；真实 SSE 与浏览器验收保留在后续任务，不声称实时能力已经实现。

## 本轮后端交付

详见 [后端节点图实施](../2026-09-28-backend-implementation/task.md)。用户限定仅后端，并取消旧版历史兼容；前端及浏览器相关混合任务保持未勾选。后端 HTTP/SSE、真实 SQLite 与进程强退已验证，不声称生产负载或浏览器验收通过。

## 前端实施与验证（2026-09-28）

- `runEventSource.ts` 解析 Workflow 的 `ready`、`progress`、`resync` SSE 帧，校验会话和业务字段；`runsApi.ts` 注入订阅并传递恢复模式、阶段、checkpoint 与请求 ID。字段与后端 `WorkflowProgress`、`SessionRecord`、`ResumeRequest`、`RecoveryQuery` 对齐：进度包含 `session_id`、`execution_epoch`、`stage`、`event`、业务 item/output/channel ID、`status`、`error`、`summary`、`result_ref`、`version`、`availability`；查询另含运行状态、当前轮次和按快照顺序排列的 `progress`。
- `useSession.ts` 在 `ready` 后查询，合并查询期间的事件；按业务身份和版本归并，隔离路由、轮次和过期查询。断线保留最后已知结果，重连再查询；同步缓冲达到 64 项上限时明确断开并要求重新同步。最终 diff 自审发现仅为旧测试注入 API 保留的 2 秒轮询分支，依据 design 4.1 的无静默降级要求删除；订阅缺失或 EventSource 不可用时明确提示并只读一次快照，后续由用户主动同步。64 与后端 `stream.py` 的观察者队列容量一致，不是业务执行并发预算。
- `RunProgress.vue` 与运行详情普通模式呈现逐项状态、连接状态、aggregate 报告及投递结果。`useRunDetail.ts` 仅在相关阶段版本变化时读取阶段正文；终态生命周期事件到达后，以最终 `SessionRecord.version` 修正全部阶段的固定版本并查询，防止结束时仍展示较早阶段版本。阶段重跑选择 collect/analyze/aggregate/notify；无 stage 续跑沿原轮次，重跑提示后续通知会再次发送，结果未知只查询确认，不自动重发操作。
- 前端全量 `48` 个测试文件、`242` 个测试通过；`npm run typecheck`、`npm run architecture:check`、`npm run build`、Prettier 检查及 `git diff --check` 通过。这些结果来自本轮前端验证；后端验证详见后端日期化 task。删除兼容轮询后另复跑 `query`、`run-stream`、`run-detail`、`runs-actions`、`runs-api`、`runs-view`，6 文件/30 测试通过（42.14 秒）；typecheck、architecture:check（213 文件及 27 个规则夹具）、build 与全量 format:check 重新通过。OpenSpec 严格校验和 diff 空白检查通过。单元测试覆盖首屏和重连竞态、旧快照和旧轮次、缓冲上限、终态核对、阶段正文版本、订阅释放及恢复参数。
- `runs-api` 现有测试主要覆盖列表查询，`runs-view` 覆盖运行列表而非运行详情；阶段重跑弹窗的全部可用性与失败交互尚无独立 UI 测试。因此 3.3 不以全量测试通过代替具体场景验收。真实浏览器中阻塞慢分支/慢渠道的端到端验收也尚无记录，3.6 与根任务 7.7 保持未完成。
- 独立审查代理检查：第一个实例报告 `Antigravity OAuth adapter does not safely support input item type agent_message`；重试和另一个小范围只读实例持续未返回报告，已停止。不能声称独立审查通过或无偏离。主代理完成最终 diff 自审：前端使用同一后端查询投影，按业务身份/版本归并，轮次经查询确认，页面释放查询和订阅，断线不取消运行；删除上述轮询兼容分支后未发现其他已确认的设计偏离。阶段正文初始读取使用当前业务版本，后端 `active_phases` 已隔离被重跑清除的下游阶段，不需要另设前端恢复状态来源。
