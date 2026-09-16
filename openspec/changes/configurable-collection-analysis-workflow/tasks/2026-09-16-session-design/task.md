# LangGraph session 与渠道生命周期设计调整

> 后续决定：本文件记录早先设计过程。“仅从 checkpoint 投影展示”的方案已由 [运行时业务存档](../2026-09-16-session-runtime-store/task.md) 取代；其他渠道/取消决定仍有效。

状态：设计已更新，实现与行为验证待执行。本文件是设计变更后的新任务，不改写原 task.md 的历史执行记录。

## 决策依据

- 2026-09-16 用户确认：session 的展示、历史与恢复依附 LangGraph；删除“不引入 checkpoint”和独立存档唯一事实来源的限制。依据 [proposal 验收与边界](../../proposal.md) 和 [总设计 §1.6、§3](../../design.md)。
- 用户确认：历史 Collector 读取 Workflow 的展示实现；因此 [SessionView](../../modules/workflow/design.md) 同时服务 API 和 [历史采集](../../modules/collection/design.md)，避免两份状态解释。
- 用户确认：渠道实例持续程序生命周期；依据 [Channel 设计](../../modules/channel/design.md)，同一配置版本复用实例，显式替换、卸载与服务关闭负责释放。配置版本区分是为满足总设计“旧快照目标不改变”，不是为每次 send 创建实例。
- 用户确认：按 session_id 取消，由 RunCoordinator 管理任务，HTTP 只转交指令；[交互设计](../../modules/interaction/design.md) 对手动和定时运行采用相同寻址方式。
- 用户要求保留 Workflow 图中 T 的原描述，本次未修改该图及 aggregate 的定义。
- 用户进一步确认：只给 Mock 增加专用 logging Handler，不新增 logging 渠道。依据 [Mock 设计](../../modules/channel/mock/design.md)，输出可读文本，每次写入结果单独记录并在调用后检查；选择该方式是为了避免全文件回读及共享 last_error，并保持代码精简。
- contracts 是设计的派生说明，不作为以上决策依据。本次保留原 AI 默认值，也不新增超时、重试、保留天数等默认值。

## 后续实施任务

- [ ] Workflow 使用 LangGraph SQLite checkpointer，以 session_id 对应 thread_id；父子图共享 checkpointer，通过 namespace 区分执行进度。删除迁移后多余的独立运行进度来源，不维持两套可写状态。
- [ ] 实现 SessionView 的列表、单个 session、阶段内容及可用性查询。列表从父图最新状态按 thread_id 去重，API 与历史 Collector 复用；图执行与状态读取解耦，避免采集模块反向依赖 WorkflowService。
- [ ] 接入 history Collector 的 Workflow/session 选择、次数、时间和 token 边界；固定一次查询选中的历史版本，无历史与正文缺失分别报告。
- [ ] 实现原 session 恢复、按 session_id 取消及启动后的 interrupted 标记；成功分支与确定投递不重跑，不确定发送意图不补发。每项结果建立持久化边界，不能仅在整个 fan-out 或通知阶段末保存。
- [ ] 将备份范围与保留规则应用到所有 checkpoint、子图和待提交写入；关闭正文保存不能由 checkpointer 绕过，清理后仍能展示摘要和缺失原因。验证当前 LangGraph 版本的序列化与清理能力，必要适配集中在 Workflow 持久化边界。
- [ ] ChannelManager 复用按快照配置绑定的常驻实例，处理并发初始化、显式替换、插件卸载及关闭；同步 [Email](../../modules/channel/email/design.md) 的连接生命周期。
- [ ] Mock 专用 Handler 追加 UTF-8 文本并 flush，为本次记录返回写入结果；send 检查后生成回执。复用 Handler 锁，隔离诊断日志，不引入额外通知类型或文件回读机制。
- [ ] [装配层](../../modules/lifecycle/design.md) 注入 checkpointer 和只读 SessionView，在关闭活动运行后释放渠道及数据库。基于已确认设计同步派生接口说明；现存代码和 contracts 不反向决定设计。

## 验证

本次仅修改设计文档，执行文档差异、引用路径和旧描述检查，不把这些检查算作实现通过。

后续实现按以下顺序验证：

1. 定向单测（每条后端测试命令硬超时 60 秒）：父子图重启恢复、session 列表去重、历史展示一致、备份范围、独立请求取消定时任务；实例复用、旧快照目标、Mock 写入/flush 失败与并发追加。
2. 受影响包的类型或 lint 检查。
3. 构建检查。
4. 最小烟测：触发并查询 session，读取其历史，跨进程重启恢复；重复发送到 Mock 后人工可读且无重复追加。
