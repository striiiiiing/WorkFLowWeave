# Workflow 模块设计（v0.1）

依据：[模块 proposal](./proposal.md)、[根 proposal](../../proposal.md) §2.1、§3，以及[根设计](../../design.md) §3.1–§3.7、§4。公共配置及结果对象使用 `logagent/models.py`，本模块统一负责流程推进和恢复策略。

## 1. 职责与结构

Workflow 解析资源引用，验证有效配置，管理手动与定时触发，按顺序组织采集、共享输入、fan-out、可选 fan-in 和通知，并将阶段进度交给存档模块保存。

| 子模块 | 建议文件 | 职责 |
| --- | --- | --- |
| 应用服务 | `logagent/workflow/service.py` | 校验、保存、触发、等待、恢复、取消和关闭。 |
| 执行图 | `logagent/workflow/graph.py` | 首版 LangGraph 阶段、并发分支和故障策略。 |
| 输入与输出编排 | `logagent/workflow/formatting.py` | 保持声明顺序，拼接共享输入、fan-in 和通知。 |
| 调度与恢复 | `logagent/workflow/scheduler.py`、`recovery.py` | 单调时钟触发、任务跟踪、恢复材料判定。 |

Collector 管理自己的来源内部处理；AI 管理模型和工具；网关负责平台协议；ArchiveStore 保存阶段数据。Workflow 不重复实现这些模块的 schema 或协议。

## 2. 技术选型（ADR）

## 3. 配置与服务契约

### 3.1 WorkflowDefinition

```json
{
  "id": "daily_review",
  "name": "每日分析",
  "sources": ["mock_source", "recent_history"],
  "analyses": [
    {"id": "summary", "ai": "review_model", "prompt": "总结全部资料：\n{input}"},
    {"id": "risks", "ai": "review_model", "prompt": "分析全部资料中的风险。"}
  ],
  "fan_in": {
    "order": ["summary", "$input", "risks"],
    "separator": "\n\n---\n\n",
    "ai": null,
    "prompt": "",
    "mark_incomplete": true
  },
  "channels": ["local_notice"],
  "input_separator": "\n\n",
  "include_counts": true,
  "collection_concurrency": 2,
  "analysis_concurrency": 2,
  "on_all_empty": "skip",
  "analysis_failure": "continue",
  "send_partial": true,
  "backup": {
    "enabled": true,
    "stages": ["snapshot", "collection", "analysis", "final"],
    "on_failure": "stop",
    "retention_days": 30
  },
  "interval_seconds": null,
  "enabled": true
}
```

`sources/channels` 是有序资源 ID 列表，分析任务中的 `ai` 也是资源 ID；配置快照会展开引用。来源和分析列表至少有一项，通知目标允许为空。来源、分析 ID 和 Channel 引用各自不能重复；两个并发上限是至少为 1 的整数。

`fan_in=null` 表示各成功分析分别输出；`order=[]` 默认使用全部分析的声明顺序。显式 `order` 只能引用存在的分析 ID，不能重复，最多出现一个 `$input`；共享输入作为整体插入。`interval_seconds` 为空或为正的有限秒数，`enabled=false` 禁止新触发并关闭定时任务。

校验同时覆盖所有来源及展开后的 Setter、AI 模型参数、工具引用、Channel 通知能力和实例配置。模板覆盖按同名 Setter 显式覆盖执行，不允许跨 Collector 使用模板。不存在或无效引用必须在保存与触发前报告字段路径。

### 3.2 WorkflowService

```python
class WorkflowService:
    async def validate(self, definition: WorkflowDefinition) -> None: ...
    async def save(self, definition: WorkflowDefinition) -> WorkflowDefinition: ...
    async def trigger(self, workflow_id: str) -> SessionRecord: ...
    async def wait(self, session_id: str) -> SessionRecord: ...
    async def resume(self, session_id: str) -> SessionRecord: ...
    async def cancel(self, session_id: str) -> SessionRecord: ...
    async def shutdown(self) -> None: ...
```

`save()` 在完整语义校验后调用 `ResourceStore.save()`；`trigger()` 读取并校验 `ResourceStore.snapshot()`，创建存档管理记录，然后提交受控执行任务。返回 session 只代表请求已接受，业务成败通过查询或 `wait()` 得到。

`snapshot()` 返回公共 `WorkflowSnapshot`，其中 `workflow: WorkflowDefinition`、`sources: dict[str, SourceConfig]`、`ai: dict[str, AIConfig]`、`channels: dict[str, ChannelConfig]` 和 `created_at` 均为本次确定的副本。来源的 Setter 已展开；图通过快照属性和资源 ID 取配置，后续阶段不重新读取 ResourceStore。`ArchiveStore.create()` 接收该完整快照。

全局运行数受 `SystemConfig.max_concurrent_runs` 限制，待运行队列有界；队列容量耗尽返回容量错误，交互层映射 429。并发准入和建档必须协调，不能留下声称会运行却未被接管的 session。

`wait()` 等待指定运行结束；调用方取消等待不取消 Workflow。`cancel()` 取消排队或运行中的任务并等待取消状态写回；对已取消记录重复调用保持幂等，其余不可取消的终态返回冲突。`shutdown()` 可重复调用，停止接收并回收全部受跟踪任务。

## 4. 执行图与状态

### 4.1 阶段与顺序

```mermaid
flowchart LR
    collect --> analyze --> aggregate --> notify --> finish
```

首版通过 LangGraph 编排以上五阶段；阶段内部使用有界协程并发，不为每条来源建立无限动态节点。图状态包含 session、不可变有效快照、有序来源结果、共享输入、有序分析结果、最终输出、投递记录及恢复材料诊断。内存 checkpoint 不能代替存档。

| 阶段 | 执行与持久化边界 |
| --- | --- |
| `collect` | 并发执行来源，按来源声明顺序整理结果；生成唯一共享输入并保存 `collection`。 |
| `analyze` | 每个任务收到完全相同的共享输入；保留每个成功、失败、超时或取消结果，保存 `analysis`。 |
| `aggregate` | 根据 fan-in 编排或分别生成输出；可再次调用 AI，保存 `final`。 |
| `notify` | 冻结最终输出，逐输出、逐目标投递并即时保存回执。 |
| `finish` | 汇总业务、投递、备份状态，持久化终态并释放并发名额。 |

每个阶段进入和完成时更新 `stage/updated_at`。分支完成即增量保存结果，阶段结束再保存声明顺序的完整列表；单个异常作为结果返回，不能使其它已完成分支丢失。时间戳为 UTC，耗时与调度使用单调时钟。

### 4.2 采集与空结果策略

`CollectorManager.collect()` 返回的 `success/empty/filtered_empty/missing/failed/timeout` 分别保留。`failed/timeout` 使用 `on_error`，`missing` 使用 `on_missing`，原始无条目使用 `on_empty`，处理后无条目使用 `on_filtered_empty`；每类策略为 `stop/skip`。

`stop` 结束当前运行并保留已取得结果；`skip` 跳过该来源并记录原因。成功文本按 `sources` 顺序用 `input_separator` 拼接。`include_counts=true` 时添加有序来源计数说明，包含原始与选择后数量及来源状态；计数由 Collector 返回，不由 Workflow 猜测。

“所有来源无内容”依据来源结果判定，不能因计数说明非空就视为有业务数据。`on_all_empty=stop` 记录无输入错误并失败；`skip` 直接结束，不调用 AI、不发送通知。只有合法空结果时可正常完成，混有跳过的来源错误则记录部分成功。

### 4.3 fan-out 与 fan-in

使用信号量执行分析；并发为 1 时实际串行，较大时允许多个请求同时等待。最终顺序始终是配置顺序，与完成先后无关。单分支失败不取消其它分支；`analysis_failure=stop` 在收集分支结果后停止下游，`continue` 允许处理已有成功结果。

fan-in 关闭时，每个成功分支成为一个输出，`output_id` 为分析 ID。存在失败分支且 `send_partial=false` 时保留结果但不发送；允许部分输出时只发送成功内容，并在 metadata 标记不完整。

fan-in 开启时，按 `order` 拼接成功分支及可选 `$input`。失败分支不填造假文本；`mark_incomplete=true` 时添加缺失任务及原因说明。该字段只控制正文标记，结构化结果始终保留失败事实。没有成功分支时不得仅把错误说明当作有效分析。

没有 fan-in AI 时，编排文本即最终结果；配置 `fan_in.ai` 时，通过同一 `AIService.execute()` 分析整段编排文本。fan-in 的内部 `task_id` 可为 `fan_in`，结果保存在独立 `final` 阶段，不混入 fan-out 分支索引。汇总输出使用稳定 `output_id=final`。

fan-in AI 失败时保留之前的分析结果，不把拼接文本静默冒充成功汇总。`send_partial` 不会放宽模型失败或缺少恢复材料的校验；首版不自动回退到另一种输出模式。

### 4.4 通知与终态

将输出映射为 `Notification(session_id, output_id, title, text, metadata)`；metadata 至少关联 Workflow、分析 ID、阶段及不完整状态，内容关联使用 session/artifact 标识，不泄漏本地绝对路径。

按输出顺序及 Channel 顺序逐对调用 `ChannelManager.publish([config], [notification])`，每次立即保存 `DeliveryResult`。以 `(output_id, channel_id)` 识别投递；已持久化 `success` 永久跳过，不能批量结束后才记录全部成功。

投递状态为 `success/failed/timeout/skipped`；禁用目标为 `skipped` 且零次尝试。SMTP 超时可能携带 `error.details.delivery_uncertain=true`，网关不自动重试此类不确定投递；显式恢复需保留该诊断。远端受理与本地回执落盘之间有不确定窗口，首版不承诺外部系统的 exactly-once。

| Session 状态 | 定义 |
| --- | --- |
| `created` | 已建档且被受控队列接管。 |
| `running` | 占用运行名额，正在推进某个阶段。 |
| `completed` | 必要阶段完成，或按合法全空跳过策略正常结束。 |
| `partial` | 有可用结果，但存在跳过的失败来源、失败分支、投递失败或备份降级。 |
| `failed` | 停止策略触发、必要阶段失败或没有可用的分析结果。 |
| `cancelled` | 接收到显式取消或正常关闭取消，停止后续阶段。 |
| `interrupted` | 启动扫描发现此前进程未正常结束的运行。 |

终态依据本次最新阶段结果汇总，历史错误列表保留但不会使已修复的失败永久阻止完成。通知失败不删除成功分析；备份完整性与业务、通知状态分别可查询。

## 5. 备份与恢复

`snapshot/collection/analysis/final` 遵循 `BackupPolicy`。`collection` 包含共享输入和来源结果；`analysis` 包含分支顺序、结果和可序列化工具事件；`final` 包含有序输出。是否已经进入通知阶段由始终保存的 `SessionRecord.output_frozen` 记录，不能只放在可关闭的 final 内容备份中。内容版本和校验由 ArchiveStore 管理。

内容写入失败先记录缺失原因，再执行 `on_failure=stop/continue`；继续时标记不能完整恢复。管理记录本身不可写时立即终止受影响运行，返回存档不可用，不继续向外发送无法记录状态的通知。

`resume()` 仅接受允许恢复的 `failed/partial/cancelled/interrupted` session，保持原 ID 和创建时间。先取得 session 独占运行权，校验完整原快照及当前可用存档，再将状态转为排队/运行；活动运行和无需恢复的完成记录返回 409。

| 待继续工作 | 必要材料和复用规则 |
| --- | --- |
| 重试分析 | 原快照、原共享输入、已成功分支内容；只执行未成功分支。 |
| 继续汇总 | 原快照、所引用成功分支；使用 `$input` 时还必须有原共享输入。 |
| 补发通知 | 原快照、冻结的最终输出、持久化投递结果；跳过全部已成功组合。 |
| 原始采集未完成或输入缺失 | 明确报告不可恢复范围，不能调用原始来源“补齐”旧输入。 |

成功分支内容缺失时不能重跑该分支；已成功 fan-in 的结果缺失时不能重跑该模型。没有必需材料时返回包含 `missing_artifacts` 和可用阶段的恢复冲突，不能改用最新模板、当前配置或新采集内容。

最终输出进入 `notify` 前在管理记录中持久化 `output_frozen=true`；冻结后的恢复只补发失败或未完成的通知，不重新分析或改写同一输出。关闭 final 备份仍可完成本次内存中的发送，但无法恢复补发，必须报告正文缺失。此前仍失败的分析保留原状态；需要重分析时显式触发新 session。冻结前可以恢复失败分支，并重新生成尚未发布的汇总。

## 6. 调度、取消与关闭

定时调度按单调时钟计算下一触发点，同一 Workflow 有排队或运行任务时跳过本次定时触发，不积累补跑。重启后从新的周期开始，不补发全部历史触发；手动和定时触发都通过 `trigger()`，共享校验与全局并发限制。

所有后台运行、调度和阶段子任务均受跟踪。取消向采集、AI、网关协程传播；已发生的外部副作用无法撤销，但取消后不得开始新的通知。关闭先停止调度和准入，再取消/等待运行，最后交由 lifespan 关闭插件和模型客户端。启动时把孤立的 `running` 及未被接管的 `created` 记录标为 `interrupted`。

## 7. 验收与依赖

测试建议位于 `tests/test_workflow.py`，使用内置 Mock、临时 ArchiveStore 和注入的可控时钟。

- 完整采集、并行分析、可选汇总和多目标通知均按声明顺序运行；两个分支接收的完整输入逐字相同。
- 来源错误、缺失、原始空、过滤后空、全空分别命中对应策略；全空 `skip` 不调用 AI 或 Channel。
- 并发上限为 1 与大于 1 时观测到正确执行行为；单分支超时不无限阻塞其它工作。
- fan-in `$input` 不可拆开；未知/重复分支、无效引用和参数在保存时失败。
- 备份关闭、写入失败、损坏、过期及丢失分别可诊断，管理记录不可用时不谎报成功。
- 修改模板和模型配置后恢复仍使用原快照；恢复不增加来源调用次数、不重跑已成功分支。
- 多目标中途失败或取消后，恢复只补未成功组合；已冻结输出保持原文，不重发成功目标。
- 定时任务不重叠、不补全部错过周期；取消与 shutdown 后无未回收任务、无后续通知。
- API 集成及十分钟离线稳定性测试记录 CPU、RSS、磁盘、完成/失败次数和未处理异常；结果由集成任务实际执行后填写。

依赖配置、存档、Collector、AI、Channel 五个模块先提供根契约入口；交互模块依赖本服务。未来执行器替换应保持阶段存档、资源快照及恢复语义；来源子集、多步 Agent、Webhook 属于 v0.2，不提前在首版定义中接受未实现字段。
