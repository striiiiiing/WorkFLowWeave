# 精简 Workflow 图执行与流式输出

## Why

现有 Workflow 已使用 LangGraph 父子图及 checkpoint，但图执行周围仍有阶段启动节点、存档包装、正文引用转换和服务协调逻辑。新的方向是让图直接表达阶段、并行和恢复边界，通过 `astream` 统一输出执行过程，减少重复协调层，并保留现有 Collector、AI、Channel 能力。

本变更有两个核心目标：

1. **精简 Workflow**：拆分为 Workflow 工作逻辑和围绕 `astream` 的消费子模块，减少重复协调与展示转发。
2. **为前端提供更实时的业务进度**：按 tags 筛选必要更新，推送 fan-out 中某一项成功、fan-in 完成、aggregate 成功、某个渠道发送成功；不等待整个子图结束，也不广播所有内部节点。及时推送允许协程调度与传输耗时。

本变更依据本次讨论及用户最终澄清形成。先前 Python 草图已移出仓库，不作为设计或实现依据；其中 ToolNode 的选型已明确撤回。

## What Changes

- 父图表达 collect、analyze、aggregate、notify、finish 阶段；节点或子图按本次调用接收所需输入，应用入口只管理触发、任务生命周期和调用图。
- Workflow 工作逻辑负责图、节点及必要业务提交；`astream` 消费子模块负责按 tags 筛选业务更新、维护 SessionStore 查询投影及向前端推送。稳定业务身份用于定位与去重；checkpointer 负责执行恢复，必须先提交的业务事实不转为异步旁路写入。
- **行为变化**：通知由全局串行改为独立投递分支并行，每个分支内部保持 `intent → receipt`。结果展示顺序稳定，外部到达顺序不再承诺。
- 复用官方 SQLite checkpointer；子图使用 per-invocation 持久化处理进程中断，父图接收结果并持久化后异步清理该次子图内部 checkpoint。
- 恢复入口统一为 resume：无 stage 接续中断运行，指定 stage 则重跑该阶段及后续流程至 finish（包括新一轮通知）；不提供单个已返回业务失败结果的节点重试或新 session/fork 功能。
- 保留 Agent 按 sessionID 主动读取结果的既有方式；复用业务存储基础能力及现有查询契约，明确采用 checkpoint 引用正文：正文按备份策略保存在 SessionStore，checkpoint 保存执行状态与结果引用。
- 对生命周期、API、历史采集和 Agent 接续仅做必要适配，不重写底层能力模块。

## Capabilities

### New Capabilities

- `workflow-stream-execution`：通过统一执行流观察父子图运行，同时保持逐项任务恢复和现有查询边界。
- `workflow-parallel-notification`：并行处理独立通知投递，保留逐条意图、回执和不确定投递语义。
- `workflow-checkpoint-resume`：原运行中断续跑、父图阶段重跑及已完成子图内部 checkpoint 的异步清理。

### Modified Capabilities

主 `openspec/specs/` 尚无可直接修改的已同步规范，因此本变更新增上述能力增量；不把历史归档中的规范假定为已经同步的主规范。本设计明确替换旧 Workflow 的全局串行通知约束，其余既有输入、提示词、备份及查询语义按设计中的兼容范围保留。

## Impact

- 主要影响 `src/logagent/workflow/` 的父子图装配、节点输入输出、通知图和运行入口。
- 必要适配涉及 lifecycle、interaction 的运行和订阅入口，以及前端 Workflow 业务进度消费；历史采集与 Agent 接续继续依赖只读查询接口。
- 本次不新增插件协议，不强制新增事件总线、独立恢复服务、幂等服务或另一套执行状态机。
- 本次交付为设计与实施任务，尚未改变运行代码；旧运行的 checkpoint 兼容性必须在图结构变更前验证。

## Sources

- 本次用户要求：围绕 `astream` 简化 Workflow；fan-out 尽可能保持原方案；ToolNode 是草图选型错误；通知保留 intent/receipt 并改为并行。
- 本轮确认：精简 Workflow 与前端实时业务进度是两个核心目标；推送粒度为 fan-out 单项、fan-in 完成、aggregate 成功和逐渠道发送结果，正文采用引用方案。
- 后续澄清：Agent 继续按 sessionID 主动读取；从阶段重跑按照LangGraph语义执行至 finish；子图采用 per-invocation 应对进程中断，已不需要的内部 checkpoint 异步删除。
- [旧 Workflow 设计](../configurable-collection-analysis-workflow/modules/workflow/design.md)。
- [分层提示词设计](../layer-workflow-prompts/design.md)、[统一调度设计](../unify-workflow-scheduling/design.md)。
- 当前 `workflow/fan.py`、`notification.py`、`graph.py`、`service.py` 的实际边界，详见本变更任务依据。
