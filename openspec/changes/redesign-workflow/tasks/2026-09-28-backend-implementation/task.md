# 后端节点图实施

依据：当前 [design](../../design.md) 第 1–7 节及三项能力规范；用户本轮明确仅负责后端，并要求精简 astream 替换后冗余的子模块。后续澄清要求以节点和依赖拼出 Workflow，不沿用阶段块外加转发壳；外部示例只用于理解图装配形态，不作为实现契约，不引入其中 ToolNode、无界线程或跳过分析等行为。

## 决策与边界

- 父图直接 START → collect 子图 → analyze 子图 → aggregate → notify 子图 → finish；保留设计的错误停止路由。删除重复 snapshot 图节点及五个 start_* 包装节点，快照在准入时只提交一次。阶段入口直接使用 next 指向业务节点的父图 checkpoint，阶段重跑用真实前驱（collect 使用 START）。
- 移除 WorkflowGraph 包装类及 `_phase_node` 分派器。各真实节点实现单独工作，公共函数只处理必要存档提交和错误边界；读结果不再重建图工厂。
- 每次后台执行一个 astream，订阅不另启执行；消费者只读取已提交引用并投影，不重复保存正文。保留必要 archive 提交以覆盖业务成功但 checkpoint 尚未提交的窗口。
- 新图版本为 workflow-stream-v1；每轮有持久 execution_epoch，所有分支、结果、通知键按轮次隔离。无 stage 续跑不隐式重试正常返回的 failed。主动阶段重跑清空下游引用并完整重做该阶段。
- 阶段入口未提供 checkpoint_id 时仅选当前轮次，不能静默选旧轮次；request_id 用于重放已受理请求，不创建第二轮发送。
- **用户后续范围调整优先于原设计兼容目标**：本次不保证旧版历史兼容，不为了旧快照、旧 checkpoint 或旧内部结构保留迁移/回退代码。删除 Workflow 旧快照迁移调用及对应兼容测试；graph_revision 仅用于拒绝不匹配执行图，不实现旧图续跑。新实现内部的固定业务版本、同轮恢复及阶段重跑仍是验收要求。proposal/design 未擅自改写；本条记录本次用户明确指令。
- 不改 collection_concurrency/analysis_concurrency/max_concurrent_runs=4、BackupPolicy 或插件实例锁。仅后端验证，前端与浏览器验收不在本次范围。

## 实施与验证

- [x] 节点图与 astream 消费、稳定进度查询/SSE。
- [x] 并行 intent/receipt 与局部失败、取消、不确定发送语义。
- [x] 阶段重跑、同轮恢复、材料检查与请求互斥/幂等。
- [x] 父图同步提交后的 namespace 异步清理及启动补扫。
- [x] 定向测试、真实 SQLite/进程强退、静态检查、构建、HTTP/SSE 烟测。
- [x] 对照 design/spec 复核差异及删除的冗余职责。

验证记录：改动前 workflow 全目录 + integration 的单次测试命令触及 60 秒硬超时，退出 124，已通过输出不代表全套完成。后续拆成独立测试批次，每条命令仍使用 60 秒硬超时。


## 最终实现与接口

这是结构性调整：仅把 `ainvoke` 换成 `astream` 会继续保留重复阶段分派、旧成功项扫描和串行通知链，因此选用实际节点图及单次流消费，必要业务存档仍同步提交。没有将整个批次包装成 ToolNode，也没有在事件消费者里调度后续节点。

- `graph.py` 直接装配父子图；`fan.py` 保留逐任务图边界；`notification.py` 为每个输出/渠道注册独立 intent → receipt 分支。原渠道实例锁不变，跨实例重叠由可控屏障测试证明。
- `recovery.py` 只核验公开父图入口及实际所需材料；`service.py` 以 `aupdate_state` 的返回配置续接新轮次，`Overwrite` 清空下游 reducer。主动重跑后的强退沿原新轮次恢复。相同 request_id 在 checkpoint 已提交但任务尚未提交时续接已受理轮次，完成后重放不再执行。
- epoch 管理事实保存所选入口的 `retained_phases` 引用。查询、逐项投影及阶段正文共用 `active_phases`，显式选择旧 checkpoint 时不会混入最近一轮的上游结果；正文过期保留不可用状态。此处只支持新图自己生成的业务历史，不实现旧版迁移。
- `checkpoints.py` 用真实 namespace、metadata.parents 和父图 loop 后继的已提交引用证明可清理。一个有界后台队列复用准入互斥；事务失败回滚并留待下个执行边界或启动补扫。无父 namespace 删除，无每次 VACUUM，无业务正文删除。
- `stream.py` 根据实际装配的 tags/namespace/node 注册映射筛选公开 updates；读取已提交引用后推送，不另写业务版本。开启模型 fan-in 时与 aggregate 是同一完成结果，只推送一次。

HTTP 契约：

| 入口/对象 | 字段和行为 |
| --- | --- |
| `POST /api/sessions/{session_id}/resume` 与 `/recover` | 可选 JSON：`stage`（collect/analyze/aggregate/notify）、`checkpoint_id`、`request_id`。无 stage 沿原轮次续跑；有 stage 重做目标及下游、产生新轮次并可能重新发送。 |
| `GET /api/sessions/{session_id}/recovery` | 接受 stage/checkpoint_id 查询参数，返回 available/reason；错误包括入口不存在、图版本不兼容、材料不可用和活动运行冲突。 |
| session 查询 | 新增 execution_epoch 和 progress；固定 version 完全由该版本条目重建。 |
| WorkflowProgress | session_id、execution_epoch、stage、event（item/aggregate/delivery/lifecycle）、status、适用的 item_id/output_id/channel_id、label、result_ref、version、availability、error、summary。summary 只含必要展示数据，不附配置或正文。 |
| `GET /api/sessions/{session_id}/events` | 注册观察者后发 ready；已提交事实发 progress；队列溢出/关闭发 resync 后断开；终态 progress 后关闭。ready 后客户端 GET 并归并期间事件。断开不取消运行，不承诺 Last-Event-ID 重放。 |

## 新默认值的依据

- 订阅者容量 64：仅是少量逐项状态的传输缓冲，不是执行并发或历史保留限制。设计第 4 节要求有界消费者；超过容量明确 resync，客户端靠查询补齐，不静默丢弃。未声称此值经生产负载调优。
- SSE 心跳 15 秒：仅维持空闲连接，不是模型或 Workflow 超时。运行可能等待长模型调用，需要无业务更新时保持连接；断线仍由重连查询恢复。
- 清理关闭等待 10 秒：仅限制非关键空间回收的收尾时间，超时记录错误并取消清理，下次启动重新核对。业务执行、必要写入及备份策略不使用此超时。
- 清理队列容量直接沿用 max_concurrent_runs，不再引入独立并发配置。既有 collection_concurrency/analysis_concurrency/max_concurrent_runs=4、BackupPolicy 及渠道超时均未漂移。

## 验证与精简证据

- 最终 Workflow 回归（排除进程组）：107 passed，17.14 秒。覆盖幂等提交窗口、当前/历史父图入口、子图/跨 session 拒绝、图版本拒绝、上游材料失效与废弃下游过期、固定历史、新轮次投影、业务错误/存储失败、取消、备份与清理。
- 集成、interaction、lifecycle、History Collector、Agent artifacts：67 passed，25.01 秒；包含真实 uvicorn TCP HTTP/SSE，不是只检查服务启动。仅一个第三方 anyio 弃用警告。
- 真实进程强退：4 项分批通过（最终 3 项批次 42.01 秒、新轮次项 15.30 秒），检查原 namespace/epoch、成功分支复用、业务提交/checkpoint 窗口、已发未确认投递不补发。整组曾触及 60 秒硬上限，按批拆分，不放宽超时。
- 慢分析/慢通知屏障证明快项、aggregate 与单渠道回执可先观察；重复消费同一引用不增加存储版本；清理删除异常的原子回滚、执行边界重试与启动补扫均覆盖。
- Ruff 通过；`uv build` 生成 wheel 与 sdist；没有配置独立 mypy/pyright。构建产物写入 `/tmp/workflowweave-redesign-workflow-dist`，不污染 worktree。
- 对照最终 diff 删除 WorkflowGraph、StageNodes 阶段分派、snapshot/start_* 图节点、旧成功项扫描、通知 previous 串行链、旧快照迁移和旧阶段名回退。原六个执行模块合计 1399 → 1358 行（含注释）；新恢复、清理、流消费模块共 444 行。新增需求使后端总代码增加，不声称总代码量减少或生产性能提升。
- proposal/design 未改，前端未改，不做浏览器测试、不提交或合并分支。原先涉及前端的混合复选项仍未完成；后端实现及真实 HTTP/SSE 验证独立完成。

最终文档与静态检查：OpenSpec 严格校验通过；Ruff 通过；diff 空白检查修正测试末尾多余空行后通过；新增文件空白、任务相对链接及无前端修改检查通过。

最终有效测试批次合计 178 项通过（107 Workflow + 4 真实进程强退 + 67 外围回归），不累计重复执行次数。

## 当前 worktree 验收补记（2026-09-29）

本记录前述“仅后端、不做浏览器”的范围是当时的阶段性记录；总任务第 13 节后续已扩展到前端与浏览器验收。当前 worktree 的前端 Vitest、类型/架构检查、构建和 Playwright E2E 结果统一记录于根 tasks 第 13 节及前端/Snapshot 任务；GPT-6 Luna max Tabbit 导航在 runtime 层关闭上下文，未将其记为浏览器通过，不覆盖或改写本记录的历史测试统计。
