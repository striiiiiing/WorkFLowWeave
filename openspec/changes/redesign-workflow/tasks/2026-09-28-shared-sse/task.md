# 前端共用 SSE 连接层设计补充

日期：2026-09-28。用户确认：“可行，写入前端设计”。本轮只更新设计与任务，回答 Agent 后端持久化内容，不修改运行代码、不运行应用测试。

## 依据与决策

以 [design 第 4.3 节](../../design.md#43-复用-agent-的-sse-连接机制) 为准。用户批准前一轮建议：复用 SSE 连接基础机制，Agent 继续事件日志重放，Workflow 继续完整轻量快照替换。

| 决策 | 源码依据与理由 |
| --- | --- |
| 从 Agent 抽取连接函数到 shared/api | [agentEventSource.ts](../../../../../frontend/src/modules/agents/api/agentEventSource.ts) 已有关闭、退避重连、连接代次与旧回调隔离；[runEventSource.ts](../../../../../frontend/src/modules/runs/api/runEventSource.ts) 重复部分职责，无需再独立实现一套 |
| URL、事件名和业务校验由适配器提供 | Agent 使用默认 message 和动态 after 游标；Workflow 设计为命名 snapshot 和完整视图，不能硬编码其中一种协议 |
| 业务消费不共用 | [useAgentSession.ts](../../../../../frontend/src/modules/agents/composables/useAgentSession.ts) 的历史加载、游标确认、事件去重和消息投影不同于 Workflow 的版本替换；抽取连接不要求改写这些语义 |
| 重连沿用 500ms 起步、5000ms 上限 | Agent 现有 RECONNECT_MIN_MS/MAX_MS 的明确数值；两个模块只采用一个连接重试所有者，避免原生重连与自建定时器并存 |
| 终态与游标由业务消费者决定 | 共用层只管理连接，不依赖 session/turn/epoch 模型，不在传输层重复实现运行状态机 |
| 解析和字段错误可见 | JSON/业务校验失败关闭本次订阅并上报，不把坏数据吞掉或伪装成断线后无限重试 |
| 抽取不计作功能精简 | design 第 7 节要求净代码减少；列出 runs、agents、shared 改动，共用代码计一次，删除重复连接实现才构成贡献 |

未变更业务能力和对外接口，不新增能力规范；现有 stream spec 的观察生命周期、错误可见和完整快照要求继续适用。proposal 无需修改。

## Agent 后端持久化核对（现状，不是迁移任务）

默认装配根为 `<data_dir>/agents/runtime/`，依据 [lifecycle/service.py](../../../../../src/workflowweave/lifecycle/service.py) 的 AgentService 参数：

- `History/<session_id>/events.jsonl`：用户消息、模型输出增量、工具执行记录与结果信封、轮次/命令状态等追加事实；[events.py](../../../../../src/workflowweave/agent/events.py) 分配事件 ID 并落盘，供 SSE 重放及工具结果判定。
- `checkpoints.sqlite`：官方 AsyncSqliteSaver 保存 Agent 图状态（包括 messages）与执行进度，供上下文接续；不等于完整 SSE 事件日志。来源为 [service.py](../../../../../src/workflowweave/agent/service.py) 的 initialize 和图装配。
- `Artifacts/<session_id>/…`：工具输出经相应脱敏处理后存档，图/事件可携带预览和 artifact_path；超过 output_bytes 时只保留带明确错误标记的部分内容，不能宣称始终保存全部输出。依据 [artifacts.py](../../../../../src/workflowweave/agent/artifacts.py)。
- `Sessions/<session_id>.json`：会话查询摘要，如状态、模型、turn、上下文预算和最近 checkpoint 信息；由 `_persist_session` 写入。
- `History/<session_id>/summaries/…md`：上下文压缩产生的摘要，依据 [graph.py](../../../../../src/workflowweave/agent/graph.py)。

模型增量由 `_stream_graph` 消费 astream_events 后 await EventLog.append；工具结果等由各业务路径写日志，当前不是统一从 checkpoint 异步归档。事件正文和 checkpoint 中的消息可能重叠。前端共用连接不改变这些持久化职责。

## 实施与验证

- [x] 补充设计 4.3、创建新日期任务、更新根任务；保留旧任务历史。
- [ ] 后续抽取共用连接，删除重复实现，保留薄适配器与现有 Agent 协议。
- [ ] 后续验证 Agent 断线游标续传、历史消息与工具展示不变；Workflow 首帧/重连快照、旧连接、错误和终态释放正确。
- [ ] 后续统计三个目录及同职责代码的实际净变化。
- [x] `openspec validate redesign-workflow --strict --no-interactive` 通过（退出码 0）；本轮 3 份文档链接、围栏与空白检查通过，限定变更目录 `git diff --check` 通过。已审查本轮改动，未触及其他变更目录。
- [x] 本轮未改生产代码，未运行应用测试。
