# Workflow任务

状态：待执行，完成后在本文件记录提交前验证结果。

依据：[Workflow设计](./design.md)、[总设计](../../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：公共模型、配置、AI、Channel/Mock/Email；历史 Collector 尚未实现时用注入协议测试。

- [ ] 将旧 SQLiteRunStore 收敛为图运行时唯一业务写入的 SessionStore；LangGraph checkpointer 单独负责执行进度，SessionView 只读业务存档。去掉独立调度、从存档猜测下一节点及 checkpoint 丢失后另起图的旧逻辑；保留用户指定 M/A/T 图。
- [ ] 为父图与采集/分析子图实现可复用存档节点工厂，以闭包参数绑定存储、作用域、阶段、条目标识/内容选择器；控制状态使用存档引用。验证同键同内容幂等返回原 version、异内容冲突、并发分支不覆盖及业务事务先提交的重放窗口。
- [ ] SessionView 提供列表/详情、阶段正文、可用性及独立 version 历史读取；每 session 一条摘要，API/history 共用，不解释 checkpoint 内部表。
- [ ] 同一 session 管理容量、互斥和任务句柄；提供提交/等待、recover/resume、cancel、shutdown，取消按 session_id 对所有触发来源生效。服务启动标记遗留 created/running 为 interrupted，不自动恢复。
- [ ] 保持完整共享输入、来源/分析并发限制、稳定顺序、失败/空策略、fan-in 及部分发送策略；分析分支须有 LangGraph 持久化任务/节点边界，不能仅在父节点内 gather 后统一保存；成功项持久化后不自动重跑。通知在发送意图业务存档事务确认提交后执行，回执逐条提交，不依赖默认异步写入时序，不确定意图不补发。
- [ ] 按 BackupPolicy 保存快照和各阶段正文；未保存正文仅留当前运行内存，全部父/子图 checkpoint 和 pending writes 均不得泄漏被禁用内容。终态按期限清理全部业务历史版本正文，保留幂等键避免重放复活，保留摘要和可用性；材料缺失明确拒绝恢复，不能重采补齐。
- [ ] 补 IntervalTrigger：手动/定时共用准入入口，enabled/interval 更新只影响后续触发，错过不集中补跑。管理状态写入失败停止新外部操作；正文备份失败按显式策略处理。
- [ ] 删除过时 argparse 直读存档入口，其用户功能由后续 HTTP CLI 接管；同步现有调用测试及示例。单进程一致性，不新增多进程执行器。
- [ ] 定向测试真实 SQLite 的跨重启/子图恢复、并行成功项复用、失败策略、投递确认窗口、取消、查询去重、备份关闭/到期内容实际删除（每命令60秒）；lint、构建、离线完整 Workflow 烟测。

本轮补充依据：用户在上述基线后明确要求“业务与 checkpointer 分离”“session 存储幂等”“作为 LangGraph 节点，闭包参数复用”；新设计决策见 [运行时业务存档任务](../../tasks/2026-09-16-session-runtime-store/task.md)。旧仅 checkpoint 投影方案不再适用。
