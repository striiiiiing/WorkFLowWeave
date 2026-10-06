# 已实施范围核对、逐项发布与 BackupPolicy 扩展

日期：2026-09-28。本轮根据用户审核修改设计及规范，不修改运行代码。依据 [design](../../design.md) 第 4、5、7 节及当前源码。旧日期任务保留历史；与本轮冲突的强制行数指标、服务端中间列表固定顺序和 BackupPolicy 仅管理长期正文的表述，以当前设计为准。

## 用户决定与依据

| 决定 | 依据与理由 |
| --- | --- |
| 取消生产代码净减少及历史行数门槛 | 用户明确指出本轮包含很多新功能，可能无法达到原精简指标；以功能、职责边界和重复实现移除验收，历史行数不再用于判定通过 |
| 先完成项先写入、先发布 | 用户明确要求其他分支尚未完成时先保存已完成结果；每项独立完成提交确认和归档，不为最终顺序增加等待 |
| 中间列表允许顺序变化，前端自行排序 | 用户确认 Vue 可以处理列表中间插入；使用稳定业务 ID/key 和原配置顺序信息作简单展示排序，继续接收完整 snapshot，不恢复增量缓存/双流归并 |
| BackupPolicy 扩展为统一数据策略 | 用户明确同意管理 checkpoint 保留期、配置快照/共享提示词、采集/分析/报告开关和期限；通知 intent/receipt、来源索引与摘要按关联记录管理 |
| 必要记录及 checkpoint 不受正文总开关关闭 | 执行恢复、投递事实及固定版本解释依赖这些记录；enabled 控制可选长期正文，checkpoint 有自己的期限，共享提示词遵循 snapshot 开关与引用寿命 |
| 不新增保留天数 | 本轮未指定 checkpoint/采集默认数值，继续待定；分析和最终报告默认不过期，配置/提示词及必要记录按关联保留，不臆造独立默认期限 |

先完成、后完成只是同一批并行任务的实际耗时差异，不是新增节点类型或调度优先级。每项确认自身已持久化再归档仍是可靠性边界，不构成等待其他分支的理由。模型输入及最终业务报告仍遵循配置声明顺序。

## 当前源码核对

以下为静态代码核对，不等同于本轮运行验收。

| 能力 | 已有实现 | 本轮仍需修改 |
| --- | --- | --- |
| 五阶段图与逐项子图 | [graph.py](../../../../../src/workflowweave/workflow/graph.py)、[fan.py](../../../../../src/workflowweave/workflow/fan.py) 已直接注册阶段及逐项分支，子图 compile(checkpointer=None) | GraphState 仍为 snapshot_ref/phases/items 引用；改内容 state、局部 schema，移除节点归档依赖 |
| 单次 astream | [service.py](../../../../../src/workflowweave/workflow/service.py) 的 _execute 已使用 subgraphs=True、durability="sync" | 消费者从观察既有归档改为确认 checkpoint 后形成长期归档，补齐与去重共用路径 |
| 并行 intent → receipt | [notification.py](../../../../../src/workflowweave/workflow/notification.py) 已为每项建立独立分支，无全局串行链 | 当前 intent/receipt 使用 archive_node；改为 checkpoint 权威，不以 SessionStore 判断发送资格 |
| 原运行续跑与阶段重跑 | service.py 的 resume 已有真实前驱 aupdate_state、新 epoch 和请求去重 | [recovery.py](../../../../../src/workflowweave/workflow/recovery.py) 仍从 SessionStore 恢复输入；改用内容 checkpoint，增加独立恢复截止 |
| 子图异步清理 | [checkpoints.py](../../../../../src/workflowweave/workflow/checkpoints.py) 已实现 namespace 删除及有界后台任务 | 适配内容归档交接、分类期限及 session 互斥，不把当前引用交接条件直接沿用为新内容条件 |
| 前端逐项进度与恢复动作 | [RunProgress.vue](../../../../../frontend/src/modules/runs/ui/RunProgress.vue) 已接入 [RunDetailPage.vue](../../../../../frontend/src/pages/runs/RunDetailPage.vue)；useRunDetail 已有阶段 resume | [runEventSource.ts](../../../../../frontend/src/modules/runs/api/runEventSource.ts) 仍为 ready/progress/resync；改完整 snapshot 及简单排序，浏览器验收仍未在本轮执行 |
| BackupPolicy | [models.py](../../../../../src/workflowweave/models.py) 现为 enabled/snapshot/collection/analysis/final、on_failure 和统一 retention_days | 扩展统一策略范围，替换统一期限并同步配置/API/UI 说明；不另建平行保留配置 |

前后端共用 SSE 层、分类正文/提示词存储仍待实施；上述既有图、通知、恢复和页面能力需要适配，不应整体标为未落地。

## 后续实施与验收

- [ ] 1. 按当前 design 适配已有执行和恢复实现，完成内容 state 与独立归档；不重复实现已有图能力。
- [ ] 2. 验证一项已提交而其他项仍运行时，该项已经归档、可读并可见；不等待排序或整阶段结束。
- [ ] 3. 完整 snapshot 提供稳定身份和原配置顺序信息；验证到达顺序变化、Vue 列表插入、重复/旧版本和最终排序，无额外条目同步状态机。
- [ ] 4. 扩展 BackupPolicy、分类清理及配置迁移；验证正文关闭不影响 checkpoint/必要记录、过期不级联删追溯关系、共享提示词不绕过 snapshot。
- [ ] 5. 验证已约定功能与职责，移除被替代实现；不以生产行数下降判定通过。后续后端测试命令硬超时 60 秒。

## 本轮验证

- [x] 静态核对源码，修正当前状态；修改现行 proposal/design/specs 和任务入口，另建本任务，未改写旧日期任务。
- [x] `openspec validate redesign-workflow --strict --no-interactive` 通过（退出码 0）；本轮 7 份文档的链接、代码围栏和空白检查通过；限定目录 `git diff --check` 通过。已审查当前契约，确认无强制行数门槛或中间列表服务端固定排序要求，BackupPolicy 范围在设计与规范一致。
- [x] 本轮仅文档变更，未运行应用测试、类型检查或构建。
