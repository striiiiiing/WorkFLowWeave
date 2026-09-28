# 原生事件最小真实链路

## 范围和依据

用户要求在 `feat/redesign-workflow` 先提交现状，再由主 Agent 完成一个子图的执行、原生事件、checkpoint/事实归档和中断恢复。重构前基线为 `880ebb4`。本轮遵循 [design](../../design.md) 第 1、3、5、6 节；不修改 design/proposal，不把尚未确认的 snapshot、连接释放或页面协议纳入实施。

这是结构修复：旧 `archive.consume()` 对每个 update 反复调用 `reconcile/alist`，图装配另有无消费者的标签注册表。目标是不变量只保留一处：LangGraph 负责 checkpoint 和恢复，storage 负责业务事实及版本，订阅只派生归档。

用户进一步明确：测试编写与运行交 GPT-6 Luna max；仅注入 sessionID，不能增加调用方 taskID 或自行接管 checkpoint 保存。原生内部 task ID 不是新增业务身份，本轮不建立提交确认引擎。

用户随后纠正实施范围：Workflow 整体按新项目格式重排，原先实现全部作为旧版。旧版由基线提交保留，当前源码只保留 `storage / graph / execution / stream` 四部分入口，调用方一并迁移，不保留根目录旧模块兼容壳。最小真实链路是本次验证的优先目标，不表示完整设计所有待讨论项已完成。

## 计划与受影响位置

- [x] 提交目标 worktree 现状，保留可回溯的重构起点。
- [ ] Luna 用真实 LangGraph 1.2.12 和官方 AsyncSqliteSaver 验证原生事件、并行与提交时序，每个测试命令硬超时 60 秒。
- [ ] 主 Agent 实现 `graph`、`execution` 和 `stream/subscriptions` 的最小链路，删除被替代的重复逻辑；storage 复用现有不可变事实事务。
- [ ] 验证取消、重新打开数据库后续跑、重复消费和漏消费补存；checkpoint 保存与执行恢复不依赖归档。
- [ ] 定向测试、静态检查、构建和最小 smoke；统一审查差异并记录实际完成范围。

## 已确认事实与边界

- 参考用户指定教程的直接 StateGraph 构图方式；不复制教程的伪代码、逐 chunk 建线程或 ToolNode 选型。
- 初始探针证实 v2 的根图 `on_chain_stream.data.chunk` 携带 `(namespace, mode, payload)`，其中包含子图 checkpoint。没有独立 `on_checkpoint` 回调。
- `on_chain_end` 的 tags 会继承到内部 Runnable，不能用 tag 出现次数分配事实版本。节点完成也不能视为 checkpoint 已提交。
- LangChain v2 事件实现内部使用无界队列；外层加有界队列不能证明整条链路有界。用户明确将其作为正常库行为，仅记录、不解决，不列为本轮阻塞项；不能擅自修改依赖私有实现。
- 保留期采用 design §5.4/§7 已确定的 checkpoint 7 天、采集 30 天、分析与报告不过期；本轮不另设事件队列容量或重试默认。原有应用并发上限 4、完成任务等待窗口 32、清理关闭等待 10 秒保持原值。业务事实按 session、epoch、类别和业务 item/output/channel 身份去重。

## 实施决策

- `storage` 拆出连接事务、不可变事实、模型、保留策略、session 查询与报告组装；报告不再由执行器拼接。已有历史归档读取保留，旧图 checkpoint 按新的 `workflow-native-v3` 明确拒绝恢复（design §6）。
- `graph` 直接使用 StateGraph 和 compiled 子图，collect/analyze 每个业务项一个 per-invocation 子图，notify 每个 output/channel 独立 intent→receipt。节点仅调用注入能力并返回内容，不读写业务归档。
- LangGraph 1.2.12 的 `astream()` 默认输出 `stream_channels_asis`，不同于 `ainvoke()` 的 `output_channels`。原生事件链路走流执行，仅有 output_schema 会让并行子图回写输入控制字段；子图用 `compiled.copy(update={"stream_channels": compiled.output_channels})` 固定局部流输出，直接注册 CompiledStateGraph。`stream_channels` 是 Pregel 公开字段，`copy()` 也是库自身 `with_config()` 使用的公开方法。不能使用 RunnableBinding 代替图对象：真实探针发现会让 `get_subgraphs()` 漏掉子图。相关上游报告：[LangGraph #6446](https://github.com/langchain-ai/langgraph/issues/6446)。
- `execution.runner.run_graph()` 只开启一轮 `astream_events(version="v2", subgraphs=True, stream_mode=["updates", "checkpoints"], durability="sync")`，统一注入 sessionID/thread_id，并明确收尾事件源。
- checkpoint 订阅只读取根事件转发的 namespace/checkpoints chunk，对 loop 完成 checkpoint 定点读取官方 saver；正常路径不调用 alist 或轮询。启动/恢复/收尾遗漏补存扫描复用同一事实追加接口。
- `CheckpointSource.task_id` 只记录 LangGraph pending writes 自带的 task ID；完整 checkpoint 来源用空值。它不是调用方注入字段，也不用于替代 session 身份。
- graph 的 output/schema 变化不兼容旧执行 checkpoint；不实现自动迁移或 fallback。外部 snapshot 协议仍按 design §4.2 待讨论，原有对外适配仅移入新 owner。

## 验证记录

待真实测试结果补充。
