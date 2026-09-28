# 实施任务

最新协议决定：[沿用现有 Snapshot](tasks/2026-09-28-reuse-snapshot/task.md)。用户确认保留完整 SessionRecord 首帧/版本替换、15 秒心跳、500–5000ms 重连、终态关闭和离页只停止观察；外部协议已确定，新内部链路的回归与浏览器验收仍待完成。

最新追加：[父图恢复查询与直接编译子图](tasks/2026-09-28-parent-state-compile/task.md)，依据用户最新明确要求移除嵌套状态展开和 stream_channels 覆盖；[业务超时与重试边界](tasks/2026-09-28-business-timeout/task.md)继续有效。原生 defer 清理结论已并入当前 design/spec，不再保留过时的独立任务入口。

最新实施入口：[构图与运行解耦](tasks/2026-09-28-runtime-context/task.md)，依据用户批准的 design §1.1；原生编译图输出配置继续采用，能力依赖迁入 Runtime Context。

当前状态：**四部分完整重构已完成当前 worktree 的定向自动化验收，旧版保存在基线 `880ebb4`。** 当前实施入口为第 13 节及 [原生事件流与模块拆分任务](tasks/2026-09-28-native-events-layout/task.md)：storage/graph/execution/stream、每个子图独立 nodes、图内 tags、metadata.sessionID、单次 astream_events、checkpoint 7 天/采集 30 天。外部 snapshot 已按用户决定沿用现有协议；内部分发机制单独处理。第 13.7（长期在线到期触发等）按本次验收要求明确排除。真实 Tabbit 浏览器导航在 runtime 层被关闭，未将其误记为通过。

2026-09-29 验收追加记录见 [intent checkpoint 提交屏障任务](tasks/2026-09-29-intent-receipt-barrier/task.md)。本轮发现并修复了 intent checkpoint 已由 LangGraph 同步提交、但唯一 `astream_events` 消费者尚未将 intent 事实追加到 `SessionStore` 时，receipt 仍提前执行的竞态；修复还记录了同步节点线程没有 event loop 的线程适配边界。13.2–13.6 已依据当前 worktree 的定向复跑验收；13.8–13.9 的自动化部分通过，但真实 Tabbit 浏览器被 runtime 阻塞，不能仅凭旧日期任务中的通过记录勾选。

第 1–12 节及既有日期任务保留历史和既有实现证据；其中 astream 主入口、逐事件全扫描确认和默认期限待定被本轮决定取代；外部完整 snapshot 曾重新讨论，最新用户决定恢复采用现有协议。已勾选不代表通过新结构验收，未勾选也不代表当前 worktree 完全没有对应代码。代码行数下降不再是验收要求。不得修改旧日期任务来覆盖其历史结论。

2026-09-28 checkpoint 设计修订另记于 [resume 与清理任务](tasks/2026-09-28-checkpoint-resume/task.md)。下列第 1–5 节保留首轮任务记录；与新设计冲突的“单项业务重试、fork 待定、Agent 读取方式待定”以新任务及当前 design 为准。

上一轮目标、推送粒度和当时的正文引用决定见 [精简与实时业务进度任务](tasks/2026-09-28-stream-progress/task.md)；正文引用决定已由本轮内容 state 契约取代，此前任务记录保留。

aggregate 成功推送的后续补充见 [aggregate 推送任务](tasks/2026-09-28-aggregate-progress/task.md)，旧实时进度任务中的三类推送点扩展为包含 aggregate。

前端 Workflow 实时执行视图的实施与验证见 [前后端联动任务](tasks/2026-09-28-frontend-live-workflow/task.md)，包含替换运行页固定轮询、订阅与查询同步、逐项展示和阶段重跑；本轮已完成自动化前端构建与 E2E，真实 Tabbit 浏览器导航被 runtime 阻塞。

## 1. 设计与草图隔离

- [x] 1.1 将旧 Python 草图移出仓库，按字节保留为文本，并标记不可作为设计或生成依据。
- [x] 1.2 编写本变更 proposal、design 和两个能力规范，记录逐项 fan-out、astream 边界和并行 intent/receipt 的决策。
- [x] 1.3 验证 OpenSpec 严格校验、文档链接和变更范围，记录真实结果。

## 2. 执行图与过程输出

- [x] 2.1 梳理 graph/fan/stages/service/nodes 中的真实持久化边界、仅展示节点及失败重试位置；以当前测试固定行为基线；用户取消旧 checkpoint 兼容要求。
- [x] 2.2 沿用逐项图任务重组 collect/analyze 的输入输出与 arrange；保留共享输入、并发上限、局部错误及稳定顺序，优先复用现有分支注册。
- [x] 2.3 将执行入口统一为 astream，保留 checkpointer、thread_id、同步持久化、原 thread 恢复和必要任务生命周期；验证父子图事件形状和取消路径。
- [x] 2.4 删除已被替代的阶段转发和展示包装，收缩存档工厂使用范围；移除 start_* 前替代其重试定位用途，避免只换函数名称却保留重复调度。
- [x] 2.5 接入最少必要的过程消费者，明确每种事实唯一写入者；处理重复观察、慢消费、断开、写失败与关闭，不新建无界线程或另一套执行状态机。

## 3. 并行通知

- [x] 3.1 将全局串接的通知图改为独立 intent → receipt 分支与统一 arrange；覆盖无目标、稳定身份及结果合并。
- [x] 3.2 保留意图提交屏障、确定回执复用、旧意图不自动补发和取消传播；验证不同实例能实际重叠发送且同实例资源锁语义不变。
- [x] 3.3 验证局部投递失败不影响其他分支、并发写不丢回执、结果展示有序而外部完成顺序不作承诺。

## 4. 外围适配与兼容

- [x] 4.1 更新 lifecycle 装配、健康/准入/关闭调用及 interaction 入口；保留 Collector/AI/Channel、插件和凭据接口。
- [x] 4.2 保持 SessionReader、历史列表、固定业务版本和阶段正文读取，验证 History Collector 与现有 Agent 接续。
- [x] 4.3 用户取消旧版历史兼容要求：删除旧快照迁移和旧阶段名回退，旧图 checkpoint 明确拒绝；新图恢复只接受真实父图入口。
- [x] 4.4 验证备份关闭、过期正文、查询重建和重启后的恢复材料检查；检查父子 checkpoint、pending writes 和流存档不泄漏禁止保存的正文。

## 5. 验证与审查

- [x] 5.1 定向单元与真实 SQLite/进程强退测试：成功分支复用、乱序归并、通知意图失败、发送后回执前退出；每个后端测试命令硬超时 60 秒。
- [x] 5.2 执行受影响范围的 Ruff/类型检查、包构建与最小集成烟测；用实际工具调用验证运行和查询，不以服务已启动代替结果。
- [x] 5.3 以可控屏障验证相同输入与持久化保障下独立通知重叠；重复观察不新增业务版本，记录测试耗时和删除的职责。未做生产负载吞吐基准，不声称性能提升比例或整体代码量减少。
- [x] 5.4 对照 design 与能力规范审查最终 diff；确认没有 ToolNode 整批替代、隐藏重采、重复发送、重复存储、未说明的配置变化或新增无用分层。

## 决策依据与默认值

| 决策 | 依据及理由 |
| --- | --- |
| 保留逐项图任务，优先沿用静态分支 | 用户最终澄清 ToolNode 是选型错误，并要求尽可能与原 fan-out 相同；当前 `src/logagent/workflow/fan.py` 已逐项注册节点，无需为统一外观更换恢复粒度 |
| 通知并行但每条仍有 intent/receipt | 用户明确要求；当前 `workflow/notification.py` 的 previous 链造成全局串行，改为分支链；图内有序不再等于外部到达有序 |
| 保留渠道实例锁 | 当前 `channel/manager.py` 的 `_Entry.send_lock` 与共享资源生命周期有关；本次用户授权并行编排，未要求重写插件资源并发协议 |
| astream 不接管 checkpoint | 当前 `workflow/service.py`、`graph.py` 与 `lifecycle/service.py` 已使用官方 saver；流消费替换执行观察方式，不能重复实现恢复 |
| 必须等待的事实仍由操作提交 | 旧 [Workflow 设计](../configurable-collection-analysis-workflow/modules/workflow/design.md) 的成功项复用、备份和不确定投递语义；异步观察无法证明意图已提交 |
| 保留查询与备份基础能力 | 当前 `protocols.py` 的 SessionReader、`collection/history.py` 与 `agent/commands.py` 依赖固定业务版本；本次范围优先减少外围修改 |
| 模型请求与调度语义不变 | [分层提示词设计](../layer-workflow-prompts/design.md) 和 [统一调度设计](../unify-workflow-scheduling/design.md)，不得回退到归档中更早的模型或 IntervalTrigger 方案 |
| 沿用已有并发与保留默认 | `models.py` 的 collection_concurrency/analysis_concurrency=4、BackupPolicy.retention_days=None，以及 SystemConfig.max_concurrent_runs=4；本次无修改预算和清理语义的依据，不采用草图 30 天/60 分钟数值 |
| 首轮待定项的后续处理 | fork 和 Agent 方案已由 [resume 与清理任务](tasks/2026-09-28-checkpoint-resume/task.md) 取代：采用阶段 resume、保留 Agent 主动读取；正文全面迁入 checkpoint 仍待定 |

## 6. Checkpoint 设计修订后的新增实施项

- [x] 6.1 按 [新增任务](tasks/2026-09-28-checkpoint-resume/task.md) 落实 per-invocation 子图持久化与原轮次中断续跑。
- [x] 6.2 实现父图阶段 resume 至 finish、新执行轮次与通知身份，不增加已正常返回 failed 节点的单项业务重试。
- [x] 6.3 实现父图提交屏障后的子图 namespace 异步清理、失败重试和启动核对；保留父图历史与业务结果。
- [x] 6.4 完成新增任务中的真实进程恢复、阶段重跑和清理竞态验证，并确认 Agent 按 sessionID 主动读取方式未改变。

## 文档整理记录

- 原 `workflow.py`、`subgraph/collectors.py` 已移至仓库外 `/mnt/d/code/LogAgent-design-notes/redesign-workflow-2026-09-28/`，后缀改为 `.py.txt`；移动前后 SHA-256 一致。外部附有废弃说明，现行设计不引用草图作为依据。
- 新设计独立于旧归档文件；未修改既有 proposal/design，也未实施运行代码。
- `openspec validate redesign-workflow --strict --no-interactive`：通过，退出码 0。
- `openspec status --change redesign-workflow --json`：proposal/specs/design/tasks 四类文档齐备，退出码 0；此状态仅表示规划完整，不表示实施任务完成。
- 相对文档链接、尾随空白及变更目录无 Python 草图检查通过；限定目录 `git diff --check` 通过（新文件尚未跟踪，其空白已另外逐文件检查）。
- 本次仅文档编写与草图移动，没有运行业务测试。后续实现验证仍按第 5 节执行。

## 7. Workflow 前端实时联动

- [x] 7.1 建立独立 worktree 并带入本变更文档，记录分支、基线与未提交修改隔离方式。
- [x] 7.2 核对现有轮询、阶段报告及恢复按钮，补充 design 第 4.1–4.3 节和两项相关能力的前端验收场景，另建本轮任务记录。
- [x] 7.3 后端只读订阅与查询进度契约完成：先提交再推送，提供 ready/progress/resync 与终态通知。首屏/重连客户端归并由前端后续实现，不复用 Agent 业务事件日志。
- [x] 7.4 在 runs 模块统一维护订阅、条目归并与连接状态，替换运行详情固定轮询；处理重复/乱序事件、旧查询晚到、轮次切换和作用域释放。
- [ ] 7.5 更新 Workflow 运行详情普通模式的逐项进度与最终报告可用性，保留配置顺序和错误状态；验证 Workflow 列表触发后进入该视图。
- [x] 7.6 适配中断续跑和阶段重跑动作、恢复可用性、再次发送说明与新轮次展示，保留原 session、历史版本及 Agent 主动读取语义。
- [x] 7.8 完成 OpenSpec 严格校验、相对链接/空白检查及文档差异审查，将真实结果写入本轮任务。

> 7.7 已从活动清单移除：其自动化与浏览器验收由 13.8–13.9 统一承接；原日期任务保留为历史证据。

## 后端实施补记

此前仅要求后端且明确不保留旧版历史兼容；现在前端实现和自动化验证已完成，真实浏览器验收因 Tabbit runtime 导航关闭而未完成，分别以 [后端记录](tasks/2026-09-28-backend-implementation/task.md) 和 [前端记录](tasks/2026-09-28-frontend-live-workflow/task.md) 为准。真实 HTTP/SSE 证据与浏览器交互证据分别记录，不相互替代。

## 8. 内容 state 与流式归档重新设计

- [x] 8.1 按用户授权修改 proposal/design 和三项能力契约，明确 checkpoint 执行权威、最小内容 state、长期归档和清理交接；另建日期任务，保留历史。
- [x] 8.2 静态核对基线与当前行数，分析前端 +717 行的功能来源、协议冗余和版本风险，记录证据及简化契约。
- [x] 8.8 完成本轮 OpenSpec 严格校验、文档链接/空白与 diff 审查，将真实结果写入日期任务。

> 8.3–8.7 已从活动清单移除：内容 state、astream 归档、resume/清理和 GET/SSE 方案已被第 13 节取代；日期任务保留为历史依据，未把取代误记为实现完成。

## 9. 前端共用 SSE 连接层

本次用户同意复用 Agent 连接机制，设计补充与依据另记于 [前端 SSE 复用任务](tasks/2026-09-28-shared-sse/task.md)，不改写此前实施任务。

- [x] 9.1 在 design 第 4.3 节明确共用连接层、两种消费协议与退避默认依据；保留 Agent 的现有行为和存储边界。
- [x] 9.2 从 Agent 抽取轻量 SSE 连接函数，两个模块使用薄适配器，删除被替代实现；游标与快照版本保留在各自消费层。源码核对确认 `frontend/src/shared/api/eventSource.ts` 被 Agent/Workflow 两适配器使用。
- [x] 9.3 实施后验证两类协议的重连、关闭、旧连接隔离、解析错误与终态；目标单元、Playwright 与 HTTP/SSE smoke 已通过，真实 Tabbit 浏览器阻塞证据转由 13.8–13.9 保留。
- [x] 9.4 完成此次 OpenSpec 和文档检查，记录实际结果；本轮不运行应用测试。

## 10. 后端共用 SSE 发送层

用户进一步要求检查后端 SSE 共用情况；现有两条路由分别实现发送，新增设计与依据见 [后端 SSE 复用任务](tasks/2026-09-28-backend-shared-sse/task.md)。

- [x] 10.1 核对两条路由，补充 design 第 4.4 节的共用帧编码、响应、心跳与资源清理边界，保留各自数据源和重连语义。
- [x] 10.2 在 interaction/sse.py 实施小型共用发送函数，两条路由调用并删除重复实现；不新增业务事件存储或广播层。源码核对确认 `encode_sse`/`sse_response` 为两条路由共用。
- [x] 10.3 实施后验证 Agent 游标/尾部补发和 Workflow 首帧/快照，检查心跳、断连、异常与资源释放；自动化 HTTP/SSE 通过，真实浏览器证据仍归 13.8–13.9。
- [x] 10.4 完成本轮 OpenSpec、文档及 diff 检查，记录结果；本轮不运行应用测试。

## 11. 分类归档、提示词索引与独立保留期

用户要求三类正文分别存储、共用提示词索引，并明确期限顺序只是通常用法，不得强制校验。依据及默认值见 [分类归档任务](tasks/2026-09-28-tiered-archive/task.md)。本节取代旧任务中的统一 retention_days 和未设期限的父图入口保留决定。

- [x] 11.1 更新设计、proposal 和相关规范：三类独立正文、不可变提示词版本、各类独立期限，分析/报告默认不过期；删除期限大小约束与冲突拒绝场景。
- [ ] 11.2 实施同一 SessionStore 内的分类正文及共用索引，保持归档事务、固定版本与内容 state 边界，去掉重复提示词和全量报告副本。
- [ ] 11.3 明确 checkpoint/采集的默认时长后实施分类过期、恢复截止与配置迁移；不校验类别间期限顺序，不复活过期数据。
- [ ] 11.4 实施后验证分类独立清理、共享提示词追溯、任意合法期限组合和恢复期限；复核职责边界及新增功能的必要复杂度，不要求代码净减少。
- [x] 11.5 完成本轮文档检查并记录；本轮未运行应用测试。

## 12. 审核澄清：已落地范围、逐项发布和统一保留策略

依据用户本轮审核及 [新增任务](tasks/2026-09-28-review-clarifications/task.md)。本节取代旧日期任务中的强制净减行数要求及中间列表固定排序要求；已实现能力以源码核对为准，不将待适配等同于尚未实现。

- [x] 12.1 核对图、astream、通知、resume、清理及前端源码，区分已有能力与待替换契约。
- [x] 12.2 撤销现行 proposal/design/specs 和活动待办中的代码净减少门槛，保留职责与功能验收。
- [x] 12.3 明确先完成项先保存和发布，中间数组顺序可变，前端使用稳定 ID 与简单排序/插入。
- [x] 12.4 按用户确认扩展 BackupPolicy 设计，覆盖 checkpoint、配置/提示词、三类正文及必要关联记录。
- [x] 12.6 完成本轮 OpenSpec 严格校验、7 份文档链接/围栏/空白检查及 diff 审查，结果见新增任务。

> 12.5 已从活动清单移除：逐项可见性、稳定排序和保留策略验收已分解到第 13 节及日期化前端任务；未把清单整理当作新增实现。

## 13. 四部分拆分与原生 astream_events

当前依据：[design](design.md) 第 1、3、4、5、6、7 节及 [本轮任务](tasks/2026-09-28-native-events-layout/task.md)。本节优先于前述历史实现选择；仅文档项可在本轮勾选。

- [x] 13.1 按用户授权更新四部分职责、子图独立 nodes、原生事件身份、存储范围与 7/30 天默认；新增任务保留决策依据。
- [x] 13.2 按目标目录重组 storage，统一事实追加/版本、三类查询、报告组装、BackupPolicy 与过期删除，保留 SessionReader 和历史查询。
- [x] 13.3 按 graph/subgraph/<阶段>/nodes 构图，图内 tags 分类，共用节点放 subgraph/nodes；保留原阶段行为，不复制教程省略逻辑。
- [x] 13.4 收拢 execution 的触发、恢复、任务生命周期与 scheduler，注入一致的 metadata.sessionID/thread_id；删除重复图调度/结果拼装。
- [x] 13.5 先验证当前库的 astream_events v2 元数据、tags 继承、父子图 chunk 和提交时序，再实现薄分发与 subscriptions；删除逐事件全扫和重复标记体系。
- [x] 13.6 确定直接异步观察者或有界发布/订阅的进程内分发方式，记录依据；订阅共享单次执行，不引入外部 broker 或第二套持久事件日志。
- [ ] 13.7 验证追加/去重、补存、快慢分支、恢复/通知、清理交接与分类期限；落实长期在线时的到期触发。（本次验收明确排除）
- [ ] 13.8 外部 snapshot 已确认沿用现有协议，依据 [新增任务](tasks/2026-09-28-reuse-snapshot/task.md)完成新内部链路的首帧/版本、重连、心跳、终态关闭和离页回归及浏览器验收；不重写现有协议。（自动化 HTTP/SSE 与 Playwright 已通过；Windows Tabbit 两次导航在约 0.7–1.2 秒后复现 `Target page, context or browser has been closed`，未收到 snapshot，浏览器项不勾选）
- [ ] 13.9 实施后按定向测试、静态检查、构建、烟测顺序验证，后端命令硬超时 60 秒；真实浏览器交 GPT-6 Luna max，最终交付统一代码审查。（自动化检查已通过；Windows Tabbit runtime 阻塞真实 run/SSE 浏览器证据）
- [x] 13.10 完成本轮 OpenSpec 严格校验、链接/围栏/空白检查及文档差异审查，将实际结果写入本轮任务。

## 13 验收记录

- 后端原生事件/图 API、并行通知、流进度、storage、HTTP/SSE、生命周期与清理/阶段恢复定向套件均通过；每条后端命令使用 60 秒硬超时。
- 进程强退恢复四个场景逐项分批通过；完整批次曾超过 60 秒硬限，拆分后每个场景均在限时内通过。
- 前端 Vitest 49 个文件、244 个测试通过；`npm run typecheck`、架构检查和 Vite 生产构建通过。隔离 Playwright E2E 17/17、现有服务链路 live smoke 1/1 通过；GPT-6 Luna max 使用 Windows Tabbit 验证服务端 `/api/health`、`/api/workflows`、`/api/sessions` HTTP 200，但在 `/workflows` 页面导航后两次复现 runtime 关闭上下文，未能收到真实 run 的 SSE `snapshot` 首帧或终态关闭，13.8/13.9 保持未勾选。
- 后端目录按 60 秒硬超时拆分复跑：Workflow 追加 44 项、interaction/lifecycle 119 项、agent 119 项、channel/collection 256 项、config 与根级测试 307 项均通过；根级两处过时断言已按 design §5.4 的 checkpoint 7 天/采集 30 天默认及既有 `WebChannelType` 内置声明修正。
- AI 完整套件为 36 passed、16 skipped、16 errors；错误全部来自缺少 `.env` 凭据配置，未伪造凭据或将环境错误当作产品失败。
- 过时的最小原生事件任务已由完整四部分任务取代并删除；其余任务文件仍承载当前设计依据或可追溯历史，未作无依据删除。
