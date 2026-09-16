# Workflow任务

状态：本轮实现与提交前验证完成，待主代理审查并提交。

依据：[Workflow设计](./design.md)、[总设计](../../design.md)及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务按设计提交 `97ebd68` 修正，旧“已完成”不代表符合新设计。

依赖：公共模型及现有 Collector/AI/Channel 注入接口；配置、具体 Channel、Mock、Email 后续替换不阻塞 Workflow。历史 Collector 尚未实现时用注入协议测试。

- [x] 将旧 SQLiteRunStore 收敛为图运行时唯一业务写入的 SessionStore；LangGraph checkpointer 单独负责执行进度，SessionView 只读业务存档。去掉独立调度、从存档猜测下一节点及 checkpoint 丢失后另起图的旧逻辑；保留用户指定 M/A/T 图。
- [x] 为父图与采集/分析子图实现可复用存档节点工厂，以闭包参数绑定存储、作用域、阶段、条目标识/内容选择器；控制状态使用存档引用。验证同键同内容幂等返回原 version、异内容冲突、并发分支不覆盖及业务事务先提交的重放窗口。
- [x] SessionView 提供列表/详情、阶段正文、可用性及独立 version 历史读取；每 session 一条摘要，API/history 共用，不解释 checkpoint 内部表。
- [x] 同一 session 管理容量、互斥和任务句柄；提供提交/等待、recover/resume、cancel、shutdown，取消按 session_id 对所有触发来源生效。服务启动标记遗留 created/running 为 interrupted，不自动恢复。
- [x] 保持完整共享输入、来源/分析并发限制、稳定顺序、失败/空策略、fan-in 及部分发送策略；分析分支须有 LangGraph 持久化任务/节点边界，不能仅在父节点内 gather 后统一保存；成功项持久化后不自动重跑。通知在发送意图业务存档事务确认提交后执行，回执逐条提交，不依赖默认异步写入时序，不确定意图不补发。
- [x] 按 BackupPolicy 保存快照和各阶段正文；未保存正文仅留当前运行内存，全部父/子图 checkpoint 和 pending writes 均不得泄漏被禁用内容。终态按期限清理全部业务历史版本正文，保留幂等键避免重放复活，保留摘要和可用性；材料缺失明确拒绝恢复，不能重采补齐。
- [x] 补 IntervalTrigger：手动/定时共用准入入口，enabled/interval 更新只影响后续触发，错过不集中补跑。管理状态写入失败停止新外部操作；正文备份失败按显式策略处理。
- [x] 删除过时 argparse 直读存档入口，其用户功能由后续 HTTP CLI 接管；同步现有调用测试及示例。单进程一致性，不新增多进程执行器。
- [x] 定向测试真实 SQLite 的跨重启/子图恢复、并行成功项复用、失败策略、投递确认窗口、取消、查询去重、备份关闭/到期内容实际删除（每命令60秒）；lint、构建、离线完整 Workflow 烟测。

本轮补充依据：用户在上述基线后明确要求“业务与 checkpointer 分离”“session 存储幂等”“作为 LangGraph 节点，闭包参数复用”；新设计决策见 [运行时业务存档任务](../../tasks/2026-09-16-session-runtime-store/task.md)。旧仅 checkpoint 投影方案不再适用。


## 本轮实现与决策依据（2026-09-16）

- 依据最新 Workflow design 的独立业务存档决策，新增 `SessionStore` / `SessionView` / `ArchiveRuntime` 与闭包存档节点；删除旧 `SQLiteRunStore` 和 `workflow.__main__` 直读存档入口。API/history 仅注入只读视图，后续 Interaction 负责 HTTP CLI。
- 父图快照、阶段、终态及采集/分析子图逐项结果共用存档闭包。通知使用独立 intent / receipt 图节点，先等待业务事务、再等待同步 checkpoint 边界、再发送；节点名使用声明顺序序号，避免合法 ID 中下划线造成拼接碰撞。业务幂等键仍用稳定逻辑身份，不依赖节点序号或 checkpoint ID。
- 依已安装 LangGraph 0.6.11 的 `ainvoke(durability="sync")` 与 saver 提交语义执行；SQLite 的同步查询通过线程执行，避免阻塞事件循环使异步 checkpointer 持锁无法提交。并发许可覆盖外部调用及本项业务存档，以保证 concurrency=1 时下一项开始前前一项已落档。
- 恢复先要求原 checkpoint、原快照以及 checkpoint 引用的业务条目存在。失败业务重试的阶段与执行代次记录在原控制 checkpoint，通过 `aupdate_state(as_node=start_阶段)` 继续；仅失败项使用新代次键，成功项复用原键，冻结输出只继续投递。该控制状态不从业务阶段标签猜测，不为缺失 checkpoint 建替代图。
- `trigger` 返回前原子创建 session 并提交快照；`wait` 返回结果。协调器保留最近 32 个完成任务（含已取出的异常）供短期等待，避免服务生命周期中无界持有正文；32 是有限等待窗口的实现默认，持久历史始终通过 SessionView 查询，不影响 session 保留期限。即时取消先让任务进入异常处理边界，再取消；采集/模型/发送实现吞掉取消时也不得进入下游。
- `IntervalTrigger` 复用 trigger，使用 monotonic 时钟；错过周期仅产生一次当前触发，下次从当前时刻起算。更新计划仅影响后续触发。无计划或暂停时最多等待 60 秒，但计划更新会立即唤醒；该默认仅控制空闲调度轮询，不改变业务超时。
- 未保存的 `WorkflowDefinition` 不再被静默替换成同 ID 的已保存定义；当前触发入口明确接受已保存 ID 或完整 WorkflowSnapshot。配置模块后续扩展临时定义快照时须显式实现。
- 备份控制不改变管理事实；缺失/损坏/到期均明确失败，write_failed + stop 重放不能越过失败。节点异常进入 LangGraph pending writes 前脱敏；存档提交后异常、终态提交后异常分别通过幂等重放及终态事件收敛。

## 提交前验证

- `rtk proxy timeout 60s .venv/bin/python -m pytest -q --disable-warnings`：352 passed，30.11 秒。包含 SessionStore 17 项、Workflow 恢复/真实模块集成/IntervalTrigger，以及三个真实 subprocess `os._exit` 场景：业务存档提交后 checkpoint 前、分析成功项后、外部通知发送后回执前。
- 此后新增 Collector 吞取消回归：定向 `-k swallow` 1 passed，1.10 秒；没有扩大测试以模拟成功路径。
- `ruff check` 本模块与相关测试通过；仅格式化 Workflow 自有文件与迁移测试。
- `rtk proxy timeout 60s uv build`：sdist / wheel 成功。
- 离线烟测：真实 PluginRegistry、CollectorManager、AIService MockProvider、ChannelManager/MockFileChannel，成功产出 JSONL，SessionView 查询 completed，同 session recover 不重复投递。首次手工烟测未走插件发现/默认展开，按真实装配顺序修正后通过，没有修改业务逻辑掩盖无效配置。
- `git diff --check` 通过；src/tests/README 不再引用 SQLiteRunStore、run_store 或旧 workflow.__main__。旧存储实现专属测试与旧 CLI 测试删除，业务恢复和强退语义迁移到新存储/查询接口。

当前限制：本模块单进程协调，不提供多进程执行器；真实 HTTP 查询/取消及完整启动装配由后续 Interaction/Lifecycle 模块实施。LangGraph 依赖产生现有弃用/序列化警告，测试无失败。
