# 实施任务

状态：前后端代码已实施；真实浏览器的慢分支/慢渠道端到端验收尚未记录。后端依据和验证见 [后端节点图实施](tasks/2026-09-28-backend-implementation/task.md)，前端实现与自动化结果见 [前后端联动任务](tasks/2026-09-28-frontend-live-workflow/task.md)。复选框只按实际交付勾选。

2026-09-28 checkpoint 设计修订另记于 [resume 与清理任务](tasks/2026-09-28-checkpoint-resume/task.md)。下列第 1–5 节保留首轮任务记录；与新设计冲突的“单项业务重试、fork 待定、Agent 读取方式待定”以新任务及当前 design 为准。

本轮目标、推送粒度和正文引用的最终决定见 [精简与实时业务进度任务](tasks/2026-09-28-stream-progress/task.md)，取代下列历史记录中的“正文全面迁入 checkpoint 仍待定”；此前任务记录保留。

aggregate 成功推送的后续补充见 [aggregate 推送任务](tasks/2026-09-28-aggregate-progress/task.md)，旧实时进度任务中的三类推送点扩展为包含 aggregate。

前端 Workflow 实时执行视图的实施与验证见 [前后端联动任务](tasks/2026-09-28-frontend-live-workflow/task.md)，包含替换运行页固定轮询、订阅与查询同步、逐项展示和阶段重跑；浏览器验收仍待完成。

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
| 必须等待的事实仍由操作提交 | 旧 [Workflow 设计](../archive/configurable-collection-analysis-workflow/modules/workflow/design.md) 的成功项复用、备份和不确定投递语义；异步观察无法证明意图已提交 |
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
- [ ] 7.7 按本轮任务完成定向测试、类型/架构检查、构建、真实 SSE 和浏览器烟测；在慢分支/慢渠道结束前验证快项和 aggregate 已可见。
- [x] 7.8 完成 OpenSpec 严格校验、相对链接/空白检查及文档差异审查，将真实结果写入本轮任务。

## 后端实施补记

此前仅要求后端且明确不保留旧版历史兼容；现在前端实现与自动化验证已完成，分别以 [后端记录](tasks/2026-09-28-backend-implementation/task.md) 和 [前端记录](tasks/2026-09-28-frontend-live-workflow/task.md) 为准。不把真实 HTTP/SSE 测试算作浏览器验收。
