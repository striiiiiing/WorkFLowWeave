# 四部分模块拆分与原生事件订阅

日期：2026-09-28。状态：设计文档修订，尚未实施本轮结构。工作区：`.worktree/redesign-workflow`，分支 `feat/redesign-workflow`。

## 授权、范围与依据

用户在持续讨论中明确四部分结构、子图目录、存储范围和原生事件方案，最终要求“写 openspec 吧，就如此了”，授权将本轮决定写入既有 [design](../../design.md)。本轮属于同一 Workflow 变更的设计细化，在原 change 新增任务，保留既有日期任务，不另外建立竞争的设计真相源。

会话选择的 `openspec/changes/restructure-agent-runtime/design.md` 属于另一项 Agent 重构，只存在于主工作区，不在目标 worktree。本轮依据持续明确的 Workflow 范围写入 `redesign-workflow`，不修改 Agent 设计，也不复制主工作区其他变更。工作区原有大量未提交源码/测试/文档，本轮只修改本任务列出的 OpenSpec 文件。

当前依据：[proposal](../../proposal.md)、[design](../../design.md)、[流式执行规范](../../specs/workflow-stream-execution/spec.md)、[恢复规范](../../specs/workflow-checkpoint-resume/spec.md)、[通知规范](../../specs/workflow-parallel-notification/spec.md)。旧任务的已通过检查只说明旧实现，不等于新结构已验收。

## 决策与默认值依据

| 决策 | 来源与理由 |
| --- | --- |
| storage、graph、execution、stream 四部分 | 用户明确给出的职责划分；不再沿原 service/archive/recovery 相互穿插的实现追加协调层 |
| `graph/subgraph/collect/nodes/` 等子图各自拥有节点 | 用户纠正目录；仅实际共用节点放 `graph/subgraph/nodes/`，不因函数同名强行抽取 |
| storage 按 MVC 提供追加、查询、过期删除接口 | 用户说明 CRUD 是习惯用语，实际不提供覆盖历史事实的任意修改；接口供流订阅和外部查询使用 |
| 报告从长期归档组装归 storage | 用户明确指定；当前 service.py 的 `_result()` 跨阶段读取逻辑应迁入唯一存储查询实现 |
| BackupPolicy 归 storage，checkpoint 7 天、采集 30 天 | 用户指定“有效期应该是7天和30天”；依既有讨论顺序分别对应 checkpoint/collection，不从经验补默认值 |
| 分析/最终报告默认不过期，期限独立 | 延续已确认 design 第 5.4 节；本轮仅给前两类确定数值，不改变共同时间起点、活动执行保护和独立配置 |
| 图内 tags，config.metadata.sessionID | 用户最后明确纠正；不把分类加入业务 state，不由发送端建立节点标签注册表。thread_id 与 metadata 从同一 session_id 生成 |
| `astream_events` 单一入口，v2 原生事件字段 | 用户明确取代 astream；当前已安装源码支持 event/name/tags/metadata/run_id/parent_ids/data，v2 为本轮字段契约依据 |
| updates/checkpoints 等具体处理在 subscriptions | 用户明确；各协程共享一次事件源，不能为多个订阅者反复调用图。继承 tags 不等于独立业务完成 |
| 不逐事件全扫描 checkpoint | 当前 archive.consume() 收到 updates 后反复 reconcile()/alist 属于待删除实现；使用原生事件身份和投影，不另建持久化确认引擎 |
| scheduler 归 execution | 用户明确；继续复用现有 APScheduler 的定时/间隔/cron，不自行替代图调度 |
| 对外 snapshot 协议继续讨论 | 用户明确将首帧、递增版本、心跳、断连释放和离页行为留待讨论，归 stream 消费范围；不把旧规范强制重新写回本轮决定 |
| 内部分发机制未最终选定 | 用户提出发布/订阅与观察者比较，最终确认原生事件信息获取；尚无明确选择直接回调或队列，不将建议冒充用户决定 |

构图参考为用户指定的 `D:\BaiduNetdiskDownload\尚硅谷大模型技术之LangGraph实战教程\3.代码\langgraph\chapter01\workflow.py`，本轮已读取。只采纳直接 StateGraph/节点/条件边和子图局部输入输出风格；其中省略实现、非可运行语法、逐 chunk 建线程和可选 fan-out/fan-in 不直接写成业务契约。aggregate 冻结结果与 finish 终态仍按现行设计保留。

## 源码证据与验证边界

- 当前 `uv.lock` 锁定 LangGraph 1.2.12；本轮读取安装目录中 `langgraph/pregel/main.py` 与 `langchain_core/runnables/base.py`：astream_events v2 使用原生 StreamEvent，config metadata/tags 可随调用传播，额外参数转给图流。
- `langgraph/pregel/debug.py` 的 checkpoint 投影包含 config、parent_config、values、metadata、next、tasks。checkpoint 流投影不等于 v2 独立 on_checkpoint 回调，不能写不存在的 API。
- `langgraph/pregel/_loop.py` 显示任务 writes 保存与输出存在异步调度；本轮只做源码核对，未运行 v2 父子图事件与 SQLite 提交时序探针。实施前必须验证，不能把节点 end 事件直接认定为已提交，也不能借此恢复全量轮询框架。
- 当前 [archive.py](../../../../../src/logagent/workflow/archive.py) 仍只用 stream_mode="updates" 并逐事件扫描；[service.py](../../../../../src/logagent/workflow/service.py) 仍含归档报告组装；[models.py](../../../../../src/logagent/models.py) 的 checkpoint/collection 默认仍为 None。本轮设计更新不代表这些实现已修改。
- 当前清理请求主要发生在启动与运行退出；长期在线的到期触发仍需实现。只确定该行为，不新增未经依据的清理周期默认值。

## 待实施任务

- [ ] 1. 按 design 第 6 节重组 storage，单一事务追加事实/分配版本，三类正文独立查询，报告仅在 storage 组装；保留外部 SessionReader。
- [ ] 2. 将 BackupPolicy 定义与期限处理归 storage，统一所有入口的 7/30 天默认，保留分析/报告不过期、旧归档原期限和明确配置迁移。
- [ ] 3. 按各子图自己的 graph.py/nodes 组织节点；真实共用节点才提取，图内声明 tags，不保留重复注册表。
- [ ] 4. 将 runner、recovery、tasks、context、scheduler 收拢至 execution；保留原快照、恢复、请求去重、取消/等待和调度语义，删除执行层报告重建。
- [ ] 5. 运行最小真实事件探针：多 session metadata、tags 继承、root/子图事件结构、原生 checkpoint/task 身份、快分支完成与提交时序；每个命令硬超时 60 秒。
- [ ] 6. 确定进程内观察者或有界队列发布/订阅，实现单一 astream_events 入口与具体订阅；无逐 chunk 全历史扫描、无无界线程/任务、不静默丢存储事实。
- [ ] 7. 用统一事实接口实现消费补存，验证重复事件、归档失败、取消、进程退出和清理交接；不重新执行模型/采集来补归档。
- [ ] 8. 实施长期在线的过期触发，验证 7/30 天边界、独立期限、未归档唯一副本及活动恢复保护。
- [ ] 9. 另行确认对外 snapshot/首帧/版本传输/心跳/断连/离页方案后补充任务与规范，再实施前端协议适配和浏览器验证。
- [ ] 10. 定向测试 → 静态检查 → 受影响构建 → 最小烟测；最终统一代码审查，检查职责删除、重复状态、隐藏回退和安全边界。

实施协作按用户约定：核心由主 Agent 完成，非核心代码交 GPT-6 Sol high，简单非代码任务及真实浏览器验证交 GPT-6 Luna max；严格单 Agent 串行交接，子 Agent 工作时主 Agent 等待，不立即重复审查无异常的委派代码，最终交付统一审查。本轮为主 Agent 单独文档修订，没有派发代码或浏览器工作。

## 本轮文档验证

- [x] 写入已确认的模块结构、原生事件契约、存储范围和默认值；snapshot 与分发方式标为待讨论。
- [x] 新增本任务，根 tasks 第 13 节作为当前入口；未改写旧日期任务或应用源码。
- [x] `openspec validate redesign-workflow --strict --no-interactive` 通过，退出码 0。
- [x] 本轮 6 份 Markdown 相对链接、围栏、尾随空白及当前决定覆盖检查通过；已审查本轮文档差异，`git diff --check -- openspec/changes/redesign-workflow` 通过。修正 proposal/根 tasks 两处原有链接，使其指向本 worktree 实际存在的旧 Workflow 设计。
- 本轮不运行业务测试、类型检查、构建或浏览器；原生事件传播/提交边界仍在后续实施验证范围。
