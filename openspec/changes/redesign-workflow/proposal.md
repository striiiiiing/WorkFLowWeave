# 精简 Workflow 图执行与流式输出

## Why

现有 Workflow 已使用 LangGraph 父子图及 checkpoint，但图执行周围仍有阶段启动节点、存档包装、正文引用转换和服务协调逻辑。新的方向是让图直接表达阶段、并行和恢复边界，通过 `astream_events` 统一输出执行过程，减少重复协调层，并保留现有 Collector、AI、Channel 能力。

本变更有两个核心目标：

1. **精简 Workflow**：拆分为 storage、graph、execution、stream 四部分，围绕原生 `astream_events` 组织订阅，删除节点存档工厂、正文引用转换和执行层的跨阶段结果重建，以职责清晰、消除重复实现和功能正确性验收，不要求生产代码行数净减少；新增功能可以带来合理的代码增长。
2. **为前端提供更实时的业务进度**：按 tags 筛选必要更新，推送 fan-out 中某一项成功、fan-in 完成、aggregate 成功、某个渠道发送成功；不等待整个子图结束，也不广播所有内部节点。及时推送允许协程调度与传输耗时。

本变更依据本次讨论及用户最终澄清形成。先前移出的 Python 草图不作为设计或实现依据，ToolNode 选型已撤回。本轮另按用户指定的教程 workflow.py 参考直接构图风格，具体节点、目录和事件契约以 design 为准，不复制草图的业务省略或线程方案。

## What Changes

- 父图表达 collect、analyze、aggregate、notify、finish 阶段；节点或子图按本次调用接收所需输入，应用入口只管理触发、任务生命周期和调用图。
- Workflow 节点直接读取必要 state 并返回内容，不读写 SessionStore；checkpointer 是执行事实的唯一权威来源。图内 tags 分类、config.metadata.sessionID 关联身份；单次 `astream_events` 供订阅协程消费原生 updates/checkpoints 等事件，调用 storage 追加长期事实，查询和报告组装也归 storage，不自建节点标记注册表或逐事件全历史扫描。
- **行为变化**：通知由全局串行改为独立投递分支并行，每个分支内部保持 `intent → receipt`。中间结果按完成先后发布，前端负责列表排序，最终结果遵循配置顺序；外部到达顺序不再承诺。
- 复用官方 SQLite checkpointer；子图使用 per-invocation 持久化处理进程中断，父图可靠接收结果且归档交接完成后异步清理该次子图内部 checkpoint；未归档的唯一内容副本不得删除。
- 恢复入口统一为 resume：无 stage 接续中断运行，指定 stage 则重跑该阶段及后续流程至 finish（包括新一轮通知）；不提供单个已返回业务失败结果的节点重试或新 session/fork 功能。
- **存储契约变化**：state 保存必要内容，避免同份正文在当前 state 中重复表示；SessionStore 改为消费 checkpoint 事实形成的长期归档，清理 checkpoint 后历史仍可读。Agent 继续按 sessionID 和固定业务版本主动读取归档。
- **分类归档与保留期**：采集、分析、最终报告独立保存，复用不可变提示词版本及来源索引。各类期限独立配置，checkpoint 默认 7 天、采集默认 30 天；分析和最终报告默认不过期，不强制校验类别间期限顺序。阶段 resume 只在 checkpoint 有效期内可用。
- **备份语义变化**：BackupPolicy 归 storage 所有，统一管理 checkpoint 保留期、配置快照/共享提示词、采集/分析/最终报告的归档开关与期限，以及通知 intent/receipt、来源索引和摘要的关联保留规则；正文备份开关不关闭执行 checkpoint，界面和配置说明必须同步。
- **实时消费边界**：update、checkpoint 存储和对外进度处理归 stream/subscriptions；外部 snapshot 首帧、版本传输、心跳、断连和离页协议留待讨论，不以现有实现作为本轮定案。内部采用直接观察者还是有界队列发布/订阅也待确定，复用单一原生事件源。
- 对生命周期、API、历史采集和 Agent 接续仅做必要适配，不重写底层能力模块。

## Capabilities

### New Capabilities

- `workflow-stream-execution`：通过统一执行流观察父子图运行，同时保持逐项任务恢复和现有查询边界。
- `workflow-parallel-notification`：并行处理独立通知投递，保留逐条意图、回执和不确定投递语义。
- `workflow-checkpoint-resume`：原运行中断续跑、父图阶段重跑及已完成子图内部 checkpoint 的异步清理。

### Modified Capabilities

主 `openspec/specs/` 尚无可直接修改的已同步规范，因此本变更新增上述能力增量；不把历史归档中的规范假定为已经同步的主规范。本设计明确替换旧 Workflow 的全局串行通知约束、正文引用存储与实时同步协议，并调整备份开关为控制长期归档；其余输入、提示词及固定版本查询语义按设计中的兼容范围保留。

## Impact

- 主要影响 `src/logagent/workflow/`：storage 管理追加事实/查询/过期删除，graph 采用 subgraph/<阶段>/nodes 与 subgraph/nodes 共用节点，execution 管理运行及 scheduler，stream 管理原生事件分发与订阅。
- 必要适配涉及 lifecycle、interaction 的运行和订阅入口，以及前端 Workflow 业务进度消费；历史采集与 Agent 接续继续依赖只读查询接口。
- 本次不新增插件协议，不强制新增事件总线、独立恢复服务、幂等服务或另一套执行状态机。
- 已落地五阶段图、单次 astream、并行通知、阶段 resume、per-invocation 恢复与子图清理，以及前端逐项进度；当前 worktree 另有未提交的内容存储与 snapshot 适配；本轮按原生事件及四部分边界重组，不能把旧验收算作新结构已完成，也不能将已有能力列为全部未实施。旧图恢复不兼容时明确拒绝，不追加旧图兼容分支；新实现应保留已有业务归档读取能力。

## Sources

- 本次用户要求：围绕原生事件流简化 Workflow；fan-out 尽可能保持原方案；ToolNode 是草图选型错误；通知保留 intent/receipt 并改为并行。
- 本轮确认：精简 Workflow 与前端实时业务进度是两个核心目标；推送粒度为 fan-out 单项、fan-in 完成、aggregate 成功和逐渠道发送结果，本轮进一步改为内容 state、checkpoint 执行权威与 stream 长期归档；后续用户取消代码行数必须下降的要求，保留消除重复职责的目标。
- 后续澄清：Agent 继续按 sessionID 主动读取；从阶段重跑按照LangGraph语义执行至 finish；子图采用 per-invocation 应对进程中断，已不需要的内部 checkpoint 异步删除。
- [旧 Workflow 设计](../archive/configurable-collection-analysis-workflow/modules/workflow/design.md)。
- [分层提示词设计](../layer-workflow-prompts/design.md)、[统一调度设计](../unify-workflow-scheduling/design.md)。
- 当前 `workflow/fan.py`、`notification.py`、`graph.py`、`service.py` 的实际边界，详见本变更任务依据。
- 本轮最终确认：使用 `astream_events`、图内 tags、`config.metadata.sessionID`；storage 按 MVC 提供追加/查询/过期删除与报告组装，BackupPolicy 默认 checkpoint 7 天/采集 30 天；子图各自拥有 nodes，共用节点放 subgraph/nodes，scheduler 归 execution。
