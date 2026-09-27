# Checkpoint、resume 与子图清理修订任务

## 状态与依据

本记录对应用户授权的新设计修订，保留根 tasks.md 中首轮任务历史。事实依据为 [当前 design 第 5 节](../../design.md)、[checkpoint/resume 规范](../../specs/workflow-checkpoint-resume/spec.md) 和本轮用户最终决定：

1. Agent 保留通过 sessionID 主动读取的方式。
2. 用 resume 表达从某个父图阶段重跑，必须执行后续流程直至 finish，不是只执行一个阶段。
3. 不增加对已正常返回 failed 业务节点的独立重试；这种场景选择所属阶段重跑。
4. 考虑进程中断后恢复，最终采用 per-invocation 子图持久化；已完成且不再需要的子图内部 checkpoint 异步删除。此前 Stateless 是讨论过程中的候选，已被最后决定取代。

## 设计任务

- [x] 1.1 更新 design、最小同步 proposal，补充 checkpoint/resume 规范；区分原轮次续跑与主动阶段重跑的新轮次。
- [x] 1.2 明确父图/子图/业务存档的职责、namespace 清理条件，以及 Agent 主动读取保持不变。
- [x] 1.3 重新执行 OpenSpec 严格校验、链接与语义一致性检查；完整记录验证范围，不把 API 存在视为运行保证。

## 实施任务（尚未实施）

- [ ] 2.1 父图使用官方 saver，collect/analyze/notify 使用 `compile(checkpointer=None)`；核验父子图直接装配、配置传播和每次调用独立 namespace。
- [ ] 2.2 原轮次中断续跑使用最新 thread 配置和原 invocation；验证已保存成功任务与 pending writes 的复用。不把 astream 的 subgraphs 参数误认为持久化选项。
- [ ] 2.3 阶段 resume 使用父图入口 checkpoint、原快照与必要上游输入，通过公开状态更新 API 建立新轮次并执行到 finish；目标阶段所有分支重做，前序阶段不重做。
- [ ] 2.4 执行轮次、恢复入口和图版本进入持久化控制状态；业务存档键区分新轮次与同轮续跑。清除下游引用时处理 reducer 合并语义，不让旧成功缓存跳过主动重跑。
- [ ] 2.5 通知使用 session/轮次/output/channel 稳定键；原轮次续跑复用回执，新轮次正常发送。旧通知键在旧轮次恢复时保持可识别，不误判为新投递。
- [ ] 2.6 HTTP resume 增加可选 stage/checkpoint_id，recover 复用同一实现；无 stage 保持当前运行续跑语义。拒绝跨 session、子图内部、已失效入口和并发运行请求。
- [ ] 2.7 以父图已提交结果为清理屏障，复用运行生命周期管理受控异步清理；候选按 invocation 合并，启动/结束核对可重新发现未处理候选。
- [ ] 2.8 在 saver 存储边界实现 namespace 删除适配，按当前 SQLite schema 原子删除 checkpoints/writes；使用原连接互斥和参数化语句，不调用整 thread 删除。
- [ ] 2.9 同一 session 的清理与恢复采用共同互斥边界；父图历史入口与业务存档保留，内部历史已清理时不再暴露为可恢复入口。
- [ ] 2.10 复用 AgentCommand/SessionReader 的现有读取路径，不传入 Workflow checkpoint，不自动改写既有 Agent 会话。

## 验证任务

- [ ] 3.1 真实进程强退：并行分支部分结果与 pending writes 已提交、其他分支尚未完成；重启沿原 namespace 续跑，成功外部调用不重复。
- [ ] 3.2 业务失败作为结果正常汇合时，无 stage 的 resume 不隐式重试；选择 stage 后整阶段重新执行。
- [ ] 3.3 从 analyze 重跑：采集调用计数不增加，全部分析、汇总、通知和 finish 计数增加；从 notify 重跑只增加本轮通知与 finish。
- [ ] 3.4 主动重跑后的进程中断：保持本轮标识，确定回执不重发，不确定回执不自动补发；旧轮次历史可按固定业务版本读取。
- [ ] 3.5 清理窗口：子图已返回但父图未提交时保留；父图提交后删除内部 checkpoint 和 writes；活动 invocation 与父图 namespace 不受影响。
- [ ] 3.6 清理竞态/错误：并发 resume、重复候选、事务中断回滚、进程退出后补扫、旧 graph_revision 和已清理子图历史的明确反馈。
- [ ] 3.7 删除已完成子图内部历史后，仍能由父图入口主动重跑；同时验证 BackupPolicy、输入过期、下游旧正文过期、Agent 固定版本读取。
- [ ] 3.8 每个后端测试命令硬超时 60 秒，随后执行静态检查、构建、最小集成烟测及差异审查；不将微型验证当作生产恢复验收。

## 决策与默认值依据

| 决策 | 依据 |
| --- | --- |
| 子图 per-invocation 而非 Stateless | 用户最后明确保留进程中断恢复；当前 LangGraph 的 compile 文档说明 None 继承父 saver，False 禁用继承；不使用跨 invocation 状态 |
| 无 stage 与指定 stage 分开 | 前者是进程中断接续，后者按用户要求从目标阶段一直执行到 finish；正常 failed 返回不是 LangGraph 挂起任务 |
| 新轮次区分主动重跑 | 主动阶段重跑需真正执行后续 notify；同轮进程恢复仍需复用确定回执。以一个稳定 execution_epoch 区分，不以正文相同或新的请求时间猜测 |
| 不增加请求时的配置覆盖 | 用户要求基于原 session 阶段重跑，未要求修改资源；沿用原快照，使入口与上游输入含义稳定 |
| 清理以父图提交为条件 | 删除发生在子图结果已经脱离内部进度后，避免失去进程恢复材料；astream chunk 不等于 checkpoint 已提交 |
| 不采用新的天数/分钟默认 | 用户要求异步删除已无用子图进度，因此按完成与提交事实触发；保留未完成调用，父图和业务保留策略沿用既有设置 |
| saver 的局部清理适配 | 已检查当前 `langgraph-checkpoint-sqlite 3.1.1`：adelete_thread 会删除整 thread；aprune/adelete_for_runs 继承的实现抛 NotImplementedError。只扩展 namespace 删除，不复制 saver 的执行机制 |
| Agent 保持主动读取 | 当前 `src/logagent/agent/commands.py::_workflow_result` 先按 sessionID 取记录，再用 record.version 读取 aggregate；按用户要求保持这一方式 |

## 检查记录与限制

- 当前环境为 LangGraph 1.2.12、SQLite saver 3.1.1。已检查 `StateGraph.compile`、`aget_state_history`、`aupdate_state`、`astream` 的签名，以及 saver 删除实现；普通恢复、阶段重放与清理不使用自行拼装的 checkpoint 私有调度结构。
- 探索性 per-invocation 微型验证曾观察到异常续跑时成功兄弟任务再次调用，尚未定位配置传播与版本行为，未作为通过证据。最终设计仍按用户要求采用 per-invocation，实施任务 3.1 必须以真实进程强退验证，不因该现象增加第二套调度或改成 Stateless。
- Stateless 候选的同步 durability 微型调用遇到当前库内部 `_put_checkpoint_fut` 异常；该候选已经撤回，不据此修改当前依赖或运行代码。
- 本轮只修改设计、能力规范和任务文件，没有实现生产代码；完整业务恢复和清理测试仍未执行。
- `openspec validate redesign-workflow --strict --no-interactive` 通过，退出码 0；相对链接、Markdown 围栏、逐文件尾随空白及草图隔离检查通过。限定目录 `git diff --check` 通过，新文件仍未跟踪，空白另由逐文件检查覆盖。
- 已检查首轮规范与新设计一致性：成功任务复用限于同轮中断续跑，主动阶段重跑含新一轮通知；fork/Agent 不再列为待定；根 tasks.md 只追加修订入口和汇总项，详细任务新建于本文件。
