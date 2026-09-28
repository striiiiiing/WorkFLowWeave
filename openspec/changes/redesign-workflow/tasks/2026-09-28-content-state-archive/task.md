# 内容 state、流式归档与前端复杂度审查

日期：2026-09-28。范围：用户授权的 OpenSpec 重新设计与静态架构审查；不修改运行代码、不运行应用测试。当前实现为 `f175e03`，历史比较基线为 `8ab64a1`。

## 授权与现行依据

用户明确要求：“未达到当初的精简指标，重新设计，改为工作流中不再保存引用，而是保存内容，但是尽可能压缩 state”“依赖 astream 来进行存储”“checkpoint 成为唯一真相源，但是会被清理，长期存储实际依赖从 astream 持久化的内容”，并要求分析前端增长原因。

本轮以 [proposal](../../proposal.md)、[design](../../design.md) 和三项当前能力规范为实施依据。原任务保留历史；旧引用方案、禁止 checkpoint 正文的备份语义、客户端 ready/query/event 归并不再是本轮要求。文档完成不代表实现验收完成。

## 决策、依据与默认值

| 决策 | 依据与理由 |
| --- | --- |
| state 直接保存内容，节点不访问 SessionStore | 用户本轮明确要求；现有 nodes.py 的 ArchiveRuntime、archive_node 和 graph.py 的成功存档路径保留了双重协调，必须删除职责而非移动 |
| 最小 state，不重复最终报告/通知正文 | 下游只需规范化输入、冻结输出和小型回执；fan-in 的 `$input` 与原配置按既有提示词契约保留，不为减行截断内容 |
| checkpoint/pending writes 决定执行，astream 消费归档 | 流更新不是持久化日志；提交识别、丢失补齐与归档事务必须共用一条归档路径，不能建立第二套执行事实 |
| 先归档再清理，保留父图交接屏障 | 旧“父图收到汇总即可删子图”会丢掉尚未归档的单项正文；长期内容、摘要或 not_saved 决定提交后才能释放最后源副本 |
| 默认保留支持阶段 resume 的父图入口 | 用户此前明确需要从某阶段执行至 finish；本轮未取消该能力，不默认清空全部 checkpoint，也不新增归档重建图的恢复模式；无新保留天数 |
| BackupPolicy 仅控制长期归档 | 内容 checkpoint 与“关闭备份禁止正文落盘”不能同时成立；本轮显式改变承诺，配置/UI 说明需同步，不能把临时 checkpoint 称作从未持久化 |
| 通知并行且 checkpoint intent→receipt | 保持先前用户决定和 ChannelManager 实例锁；归档不再参与发送准入，遗留意图无确定回执仍为 delivery_uncertain |
| 每个必要业务点发完整轻量 snapshot | 用户要求逐项即时可见而非特定增量协议；现协议导致前端协调查询和事件、条目版本与阶段读取，完整元数据视图可移除此类职责 |
| content_version 由后端明确提供 | useRunDetail.ts 目前从分析/aggregate 事件推导前序阶段版本，增加重复请求与前后端耦合；保留 Agent/History 的固定业务版本接口 |
| session-wide version 不改成 epoch 比较或另加 UI revision | 旧接口已有 session 单调版本；复用原版本事务表达 skipped/expired 等变化，原 content_version 不变，避免平行版本源 |
| 并发与备份默认不变 | models.py 中 collection_concurrency/analysis_concurrency/max_concurrent_runs=4、BackupPolicy 默认开启且 retention_days=None；本轮没有修改这些数值的依据 |
| 不新增固定归档延迟与容量默认 | 采用有界消费、复用已有容量并在实施时记录；没有性能测量，不从草图或经验虚构 SLA、保留天数或压缩比例 |

待实施核实的库边界：必须证明当前 LangGraph 版本能够在慢兄弟分支结束前确认快任务的已提交 pending writes，并识别其结果与业务身份。`durability="sync"` 和收到 updates 本身不足以证明这一点；不虚构提交回调，不以整阶段等待静默削弱实时要求。本轮未运行库时序测试。

## 行数基线与验收口径

按 git 指定提交中的生产源码计算物理行/非空行，包含 Python、TypeScript、Vue（含样式）；不含测试、文档和生成物。原六文件为 service.py、graph.py、fan.py、notification.py、nodes.py、stages.py。

| 范围 | 8ab64a1 物理/非空 | f175e03 物理/非空 | 物理行净增 |
| --- | --- | --- | --- |
| 原六个执行模块 | 1399 / 1230 | 1358 / 1194 | −41 |
| Workflow 全目录 | 1988 / 1749 | 2387 / 2099 | +399 |
| 前端 runs | 1018 / 1001 | 1735 / 1690 | +717 |

后端必须连同移出的同职责代码低于原基线的两个口径；外围必要适配另列，不能挪出目录逃避统计。前端必须低于当前两个口径，并解释相对旧版新增的必要 UI/API 功能。仅局部文件减少、排版压缩或测试通过均不能证明达标。本轮只确定指标，没有宣称代码已减少。

## 前端增长来源与架构结论

依据 `git diff --numstat 8ab64a1 f175e03 -- frontend/src/modules/runs`，净增严格相加为 717：

| 文件 | 净增行 | 新增职责与处置 |
| --- | ---: | --- |
| composables/useSession.ts | 200 | ready 后查询、事件缓存、条目合并、查询/连接/页面三套代次、递归重同步；改为 snapshot 版本替换和单一连接生命周期 |
| model/progress.ts | 145 | 业务身份、版本合并、状态映射和文案；删除合并职责，保留必要状态与展示文案，不能把全部 145 行都算冗余 |
| api/runEventSource.ts | 119 | SSE 传输、数据校验及终态连接处理；传输与边界校验仍需要，简化协议并收拢重复生命周期管理 |
| ui/RunProgress.vue | 139 | 真正新增的逐项进度 UI，含样式；实时展示要求直接产生，不能靠删除功能达标 |
| composables/useRunDetail.ts | 58 | 阶段正文版本推断、报告刷新及阶段重跑；移除推断，保留报告和重跑能力 |
| api/runsApi.ts | 22 | 订阅、阶段 resume 等 API 适配，按新协议收缩 |
| model/types.ts | 19 | 进度与投递等接口模型，必要字段仍需保留 |
| composables/useRunActions.ts | 7 | 新重跑动作，保留必要业务行为 |
| ui/RunActions.vue | 5 | 重跑交互，保留 |
| public.ts | 3 | 模块导出，按实际 API 调整 |

前三项合计 **464 行，占净增约 65%**，集中于实时传输与客户端同步；其中只有双流归并和重复协调属于可删除职责，SSE 接入、校验和展示文案本身不是多余。进度 UI 139 行、详情逻辑 58 行，其余接口/动作/模型 56 行。

结论是**协议和状态归属存在架构问题，但 717 行并非全是过度包装**。旧契约主动要求 ready→GET→缓存事件→逐项归并→终态再 GET；前端实现承担了这份复杂度，不能只归因于前端写法。以完整轻量快照替换这套协议，才是在删除问题源头；把同步代码搬到 shared 或继续添加更细版本判断不会达到精简目的。正文进入 checkpoint 只简化后端执行，本身不会自动减少前端代码，必须同时调整观察接口。

静态证据：

- [useSession.ts](../../../../../frontend/src/modules/runs/composables/useSession.ts) 的 generation/connectionGeneration/queryGeneration、64 项 buffered Map、synchronize 递归和终态再查询相互耦合；需要同步的是同一服务端运行视图，却在客户端建立多路状态协调。
- [progress.ts](../../../../../frontend/src/modules/runs/model/progress.ts) 的 `mergeSessionSnapshot` 用新查询作为底再合入旧缓存；`mergeProgress` 允许相同条目 version 覆盖。因此终态查询中的 skipped（与旧 pending 都为 null version）会被旧 pending 覆盖，expired 也可能被同 content version 的 available 覆盖。此为源码静态推导，本轮未执行复现测试。
- [stream.py](../../../../../src/logagent/workflow/stream.py) 的终态投影将 pending 改为 skipped，说明变化不必产生新的条目正文版本；这也是客户端只比条目版本无法判断新旧的具体原因。
- [useRunDetail.ts](../../../../../frontend/src/modules/runs/composables/useRunDetail.ts) 的 phaseVersions 根据每个分析项推进 collect 读取版本、根据 aggregate 推进多个阶段，反映 API 没有明确给出各阶段已可读正文的版本。
- [runEventSource.ts](../../../../../frontend/src/modules/runs/api/runEventSource.ts) 与 useSession 都处理终态/连接关闭；新契约下保留单一生命周期归属，传输层负责解析和错误上报。

取舍：每个业务点携带完整元数据视图会增加带宽，大小随条目数增长；不推正文、配置、token 或所有内部节点。归档先提交再发布，有存储延迟；执行与归档并行但受有界背压。存储会短暂同时有 checkpoint/归档正文，保留阶段入口也会保留必要输入，不能声称零双写或所有 checkpoint 都会删除。

## 新增实施任务（未实施）

- [ ] 1. 按 design 的图和局部 schema 删除引用存储执行路径，直接返回内容；给出 state 重复正文审查和真实删除职责清单。
- [ ] 2. 核实 LangGraph 提交识别；使用单一幂等归档路径处理实时消费和 checkpoint 补齐，落实事务版本及有界背压。
- [ ] 3. 将 intent/receipt 权威迁至 checkpoint；验证确定回执复用、遗留意图不重发及新 epoch 正常通知。
- [ ] 4. 以真实父图入口恢复至 finish；实现父图/归档双交接后的异步清理，保护唯一副本、活动恢复与保留入口。
- [ ] 5. 更新 BackupPolicy 说明、配置界面和 schema 版本；归档未保存/过期与执行恢复边界明确，保留 Agent 主动读取。
- [ ] 6. 用完整轻量 snapshot 统一 SSE/GET 投影，明确 content_version/availability；删除客户端双流归并、缓存和阶段版本推断，保留功能 UI。
- [ ] 7. 后续实施验证中断、归档失败、去重、清理竞态、阶段重跑、首帧竞态、旧连接、新轮次、skipped/expired 及报告及时可读；每条后端测试命令硬超时 60 秒。
- [ ] 8. 按原基线和当前实现复算物理/非空行，包含迁出的同职责代码；未达标明确报告，不能用架构分层解释代替指标。

## 本轮文档验证

- [x] 用户已授权重新设计；修改设计后新增本任务，根 tasks 标明历史任务被取代的部分。
- [x] 对照实现与 git numstat 完成前端增长静态审查；未修改生产代码。
- [x] `openspec validate redesign-workflow --strict --no-interactive` 通过，退出码 0。
- [x] 7 个新增/修改 Markdown 文件相对链接、代码围栏和尾随空白检查通过；`git diff --check` 通过。已审查设计/规范/任务差异，旧任务明确标记为历史，生产代码未改动。
- [x] 遵循用户约束，不运行应用测试、类型检查或构建；运行行为和库时序留给后续实施验证。

## 本次执行进度

- 工作区 `feat/redesign-workflow`，已带入主工作区最新已批准设计；未重新设计或改写 design。
- 真实 SQLite saver 探针确认：fast pending writes 可在慢分支屏障释放前读取，含 task/checkpoint 身份；updates 到达仍需另行确认持久化。
- 采用已有 session version 作为完整快照顺序；`ArtifactInfo.content_version` 明确正文读取版本，`WorkflowProgress.order` 为运行快照中原声明位置。SSE 仅发送命名 `snapshot` 的完整 SessionRecord。
- 默认时长仍待用户指定 checkpoint/collection，分析/final 不过期；不擅自写入天数。
- 后端共享 SSE 发送层已由 Sol 实施，18 个定向测试通过；最终统一审查尚未执行。

### 恢复边界核对（执行中）

- 依据 design 第 5.1 节和 checkpoint-resume 规格，用户再次确认：业务超时/失败正常返回结果，不抛给 Pregel 以触发恢复；仅显式阶段重跑重新执行业务。执行中断才使用原 checkpoint 续跑。
- 已撤销临时 resume_items 缓存绕过，节点继续直接读取内容 state，不增加单项业务重试机制。
- Luna 只读核对确认 LangGraph 1.2.12 子图配置写入 checkpoint_id=None，而内部以键存在判断 replay，阻止复用成功 pending writes。中断恢复仍待解决；不把它当作业务失败重试。
- Luna 定向 namespace 原子删除测试通过；旧 SessionStore 测试的 retention_days fixture 需迁移到分类策略，尚未通过。

- LangGraph 调用边界已规范化：通过公开子图 ainvoke 调用，仅省略空 checkpoint_id，不改变真实 ID 的阶段重放、不修改依赖源码；已撤销所有 resume_items 缓存。Luna 验证 cleanup 5/5、stage_resume 11/11、stream/events 7/7 通过。
- 旧 ArchiveRuntime/archive_node 正文引用与缓存实现已删除；旧测试必须改验 checkpoint 权威、独立正文投影与分类保留，不能保留兼容执行路径。
