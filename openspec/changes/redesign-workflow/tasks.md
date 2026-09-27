# 实施任务

状态：设计与规范已完成并通过校验；运行代码待实施。复选框只按实际交付勾选。

2026-09-28 checkpoint 设计修订另记于 [resume 与清理任务](tasks/2026-09-28-checkpoint-resume/task.md)。下列第 1–5 节保留首轮任务记录；与新设计冲突的“单项业务重试、fork 待定、Agent 读取方式待定”以新任务及当前 design 为准。

本轮目标、推送粒度和正文引用的最终决定见 [精简与实时业务进度任务](tasks/2026-09-28-stream-progress/task.md)，取代下列历史记录中的“正文全面迁入 checkpoint 仍待定”；此前任务记录保留。

aggregate 成功推送的后续补充见 [aggregate 推送任务](tasks/2026-09-28-aggregate-progress/task.md)，旧实时进度任务中的三类推送点扩展为包含 aggregate。

## 1. 设计与草图隔离

- [x] 1.1 将旧 Python 草图移出仓库，按字节保留为文本，并标记不可作为设计或生成依据。
- [x] 1.2 编写本变更 proposal、design 和两个能力规范，记录逐项 fan-out、astream 边界和并行 intent/receipt 的决策。
- [x] 1.3 验证 OpenSpec 严格校验、文档链接和变更范围，记录真实结果。

## 2. 执行图与过程输出

- [ ] 2.1 梳理 graph/fan/stages/service/nodes 中的真实持久化边界、仅展示节点及失败重试位置；以当前测试和旧 checkpoint 固定兼容基线。
- [ ] 2.2 沿用逐项图任务重组 collect/analyze 的输入输出与 arrange；保留共享输入、并发上限、局部错误及稳定顺序，优先复用现有分支注册。
- [ ] 2.3 将执行入口统一为 astream，保留 checkpointer、thread_id、同步持久化、原 thread 恢复和必要任务生命周期；验证父子图事件形状和取消路径。
- [ ] 2.4 删除已被替代的阶段转发和展示包装，收缩存档工厂使用范围；移除 start_* 前替代其重试定位用途，避免只换函数名称却保留重复调度。
- [ ] 2.5 接入最少必要的过程消费者，明确每种事实唯一写入者；处理重复观察、慢消费、断开、写失败与关闭，不新建无界线程或另一套执行状态机。

## 3. 并行通知

- [ ] 3.1 将全局串接的通知图改为独立 intent → receipt 分支与统一 arrange；覆盖无目标、稳定身份及结果合并。
- [ ] 3.2 保留意图提交屏障、确定回执复用、旧意图不自动补发和取消传播；验证不同实例能实际重叠发送且同实例资源锁语义不变。
- [ ] 3.3 验证局部投递失败不影响其他分支、并发写不丢回执、结果展示有序而外部完成顺序不作承诺。

## 4. 外围适配与兼容

- [ ] 4.1 更新 lifecycle 装配、健康/准入/关闭调用及 interaction 入口；保留 Collector/AI/Channel、插件和凭据接口。
- [ ] 4.2 保持 SessionReader、历史列表、固定业务版本和阶段正文读取，验证 History Collector 与现有 Agent 接续。
- [ ] 4.3 使用旧图产生的真实 SQLite checkpoint 检查节点/namespace/next/tasks 兼容；记录旧通知中间状态的处理，不以业务标签猜测恢复位置。
- [ ] 4.4 验证备份关闭、过期正文、查询重建和重启后的恢复材料检查；检查父子 checkpoint、pending writes 和流存档不泄漏禁止保存的正文。

## 5. 验证与审查

- [ ] 5.1 定向单元与真实 SQLite/进程强退测试：成功分支复用、乱序归并、通知意图失败、发送后回执前退出；每个后端测试命令硬超时 60 秒。
- [ ] 5.2 执行受影响范围的 Ruff/类型检查、包构建与最小集成烟测；用实际工具调用验证运行和查询，不以服务已启动代替结果。
- [ ] 5.3 在相同并发、输入和持久化保障下比较通知重叠执行、存储写入次数、耗时和删除的重复职责；不预设性能提升比例或代码行数目标。
- [ ] 5.4 对照 design 与能力规范审查最终 diff；确认没有 ToolNode 整批替代、隐藏重采、重复发送、重复存储、未说明的配置变化或新增无用分层。

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

- [ ] 6.1 按 [新增任务](tasks/2026-09-28-checkpoint-resume/task.md) 落实 per-invocation 子图持久化与原轮次中断续跑。
- [ ] 6.2 实现父图阶段 resume 至 finish、新执行轮次与通知身份，不增加已正常返回 failed 节点的单项业务重试。
- [ ] 6.3 实现父图提交屏障后的子图 namespace 异步清理、失败重试和启动核对；保留父图历史与业务结果。
- [ ] 6.4 完成新增任务中的真实进程恢复、阶段重跑和清理竞态验证，并确认 Agent 按 sessionID 主动读取方式未改变。

## 文档整理记录

- 原 `workflow.py`、`subgraph/collectors.py` 已移至仓库外 `/mnt/d/code/LogAgent-design-notes/redesign-workflow-2026-09-28/`，后缀改为 `.py.txt`；移动前后 SHA-256 一致。外部附有废弃说明，现行设计不引用草图作为依据。
- 新设计独立于旧归档文件；未修改既有 proposal/design，也未实施运行代码。
- `openspec validate redesign-workflow --strict --no-interactive`：通过，退出码 0。
- `openspec status --change redesign-workflow --json`：proposal/specs/design/tasks 四类文档齐备，退出码 0；此状态仅表示规划完整，不表示实施任务完成。
- 相对文档链接、尾随空白及变更目录无 Python 草图检查通过；限定目录 `git diff --check` 通过（新文件尚未跟踪，其空白已另外逐文件检查）。
- 本次仅文档编写与草图移动，没有运行业务测试。后续实现验证仍按第 5 节执行。
