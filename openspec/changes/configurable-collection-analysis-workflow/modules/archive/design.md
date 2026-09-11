# 运行记录与存档模块：设计

依据 [模块提案](./proposal.md)、[总体设计](../../design.md) §1.6、§3.6 和 [配置模块设计](../configuration/design.md)。
实现位于 `logagent/archive.py`，公共模型复用 `logagent/models.py`。

## 1. 系统架构

### 1.1 职责与调用关系

`ArchiveStore(root)` 管理 session、阶段内容、可用性和过期清理。
Workflow 写入阶段产出并决定执行与恢复；历史 Collector 和 API 只读取已有数据。
存档模块不依赖 Collector、AI、Channel 或 LangGraph 的具体实现。
首版由 LangGraph 执行 Workflow，但跨进程恢复以此处的持久化数据为准。

### 1.2 每个 session 的文件布局

| 文件 | 内容 |
| --- | --- |
| `record.json` | 格式版本、备份策略、`SessionRecord` 与内部存储元数据 |
| `snapshot.json` | 序列化后的 `WorkflowSnapshot` |
| `collection.json` | 完整共享输入、来源声明顺序和各 `CollectionResult` |
| `analysis.json` | 分支声明顺序、各 `AnalysisResult`，包括成功与失败 |
| `final.json` | 最终有序输出及其 output ID，含需要发送的确定内容 |

目录为 `<root>/<session_id>/`，只允许合法 ID 和四个固定内容名称。
建议启动入口传入 `data_dir/sessions`；Store 不接受调用者提供任意内容路径。
`record.json` 的存储封套保存 `format_version` 和 `backup`，公开读取返回 `SessionRecord`。
备份策略独立于 snapshot 保存，关闭配置备份后仍能判断范围与保留期限。
管理记录保存摘要、错误、投递记录和索引，不复制被关闭备份的正文或凭据。
四个阶段的 JSON 正文严格使用总体设计 §3.6 的固定字段；snapshot 是 WorkflowSnapshot，collection 使用 shared_input/results，analysis 使用 order/results/events，final 使用 outputs/fan_in。正文不另套执行器专用对象。

## 2. 技术选型（ADR）

待后续讨论。

## 3. 接口契约

### 3.1 Store 协程入口

| 方法 | 返回与语义 |
| --- | --- |
| `create(workflow_id, snapshot, backup)` | 新 `SessionRecord`；snapshot 必须为 `WorkflowSnapshot` |
| `get(session_id)` | 独立的 `SessionRecord` 模型副本 |
| `list(workflow_id=None, limit=...)` | 按创建时间倒序、ID 打破同时间并列的记录列表 |
| `update(session_id, **changes)` | 更新后的 `SessionRecord`，未知字段和非法状态拒绝 |
| `save_artifact(session_id, name, content)` | `True` 表示已保存，`False` 表示策略禁用或范围排除 |
| `load_artifact(session_id, name)` | 已核验的 JSON 内容；不可用时抛结构化错误 |
| `availability(session_id)` | `available/missing_artifacts/recoverable` 的结构化结果 |
| `expire()` | 已处理 session 与过期内容的汇总，便于日志与验证 |

所有方法为协程；文件读写、哈希和 JSON 编解码移交工作线程执行。
快照序列化使用模型的 JSON 模式；读取者通过 `WorkflowSnapshot.model_validate` 显式重建。
`create` 校验 snapshot.workflow.id 与 workflow_id 一致，再分配合法唯一 ID。
先保存管理记录，再尝试按策略保存 snapshot，不因内容备份失败删除已创建的记录。
snapshot 内容写失败记入缺失与错误后返回记录，由 Workflow 依据 on_failure 决定是否运行。
管理记录自身无法建立或更新则抛存档不可用错误，映射 HTTP 503。
记录不存在对应 404；材料不足、非法阶段修改和冻结输出冲突对应 409。

### 3.2 状态与更新边界

session 状态为 `created/running/completed/partial/failed/cancelled/interrupted`。
阶段使用总体执行图的 `collect/analyze/aggregate/notify/finish`，不新增另一套执行图。
Store 保存状态，不自行认定模型、通知或整个 Workflow 已经成功。
`id/workflow_id/created_at` 不允许通过 update 改写；updated_at 由 Store 更新。
update 在锁内读取最新记录，再应用指定字段，不能拿旧整份记录覆盖其他更新。
来源/分支摘要与内容正文分离，失败或超时必须保留原状态和错误原因。
投递状态使用 `success/failed/timeout/skipped`，`delivery_uncertain` 保存在 `error.details` 中。
每条回执返回后 Workflow 立即保存；不能只在全部 Channel 完成后一次性写回。
启动阶段扫描遗留 running 记录并标为 interrupted，不自动调用 resume 或重新触发来源。
同一进程尚存活的运行不参与上述启动扫描；恢复执行仍由 Workflow 服务管理。

### 3.3 原子写入与完整性

1. 在 session 锁内读取记录、备份策略和现有索引，检查阶段是否允许写入。
2. 将内容序列化为确定的 UTF-8 JSON 字节，计算 SHA-256 与字节长度。
3. 写入同目录临时文件，flush/fsync 后原子替换目标内容文件。
4. 内容提交成功后，原子更新 record 索引中的哈希、长度、写入时刻与可选过期时刻。
5. 清理临时文件；失败时尽力记录 write_failed，向调用者报告错误。

索引只登记成功落盘的内容；内容与 record 是两个文件，不能声称具有跨文件事务。
若内容落盘后索引提交失败，孤立文件或哈希不匹配必须视为不可恢复材料。
读取不因文件“碰巧存在”而自动接受未索引内容，也不自动修补成成功记录。
load 同时验证索引存在、文件存在、长度、哈希、JSON 解析和格式版本。
格式不支持、JSON 损坏与哈希不符均提供可识别原因，不当作正常空内容。
错误信息只包含 session、阶段及可修正原因，不包含存档正文、凭据或任意堆栈。

### 3.4 备份范围与缺失原因

`BackupPolicy.enabled=False` 时不保存任何四阶段正文，管理记录仍然保存。
enabled 为真时只保存 stages 中指定的内容；不自动扩大范围来假装支持恢复。

| 原因 | 含义 |
| --- | --- |
| `disabled` | 用户关闭内容备份 |
| `out_of_scope` | 当前阶段未被纳入 stages |
| `not_created` | 该阶段尚未生成，不等于执行失败 |
| `missing` | 索引记录存在，但对应文件缺失 |
| `expired` | 已达到保留期限或按策略清除 |
| `corrupt` | 哈希、长度、JSON 或必要结构校验失败 |
| `write_failed` | 内容持久化尝试失败 |

availability 返回可用阶段名称列表、`missing_artifacts: dict[str, str]` 与 recoverable；缺失映射以阶段名为键、原因为值，错误详情可以补充说明。
尚未达到的阶段、被策略跳过的最终阶段，不因 not_created 自动把业务标为失败。
内容保存失败先更新可用性；Workflow 采用 on_failure=stop/continue 决定业务推进。
若连缺失记录也无法更新，直接暴露存档不可用，不能返回“完整可恢复”。

### 3.5 恢复所需材料与输出冻结

恢复至少需要原 snapshot；来源、AI 和 Channel 的最新资源不能替代该快照。
继续分析需已有 collection 共享输入；读取它不得重新调用采集源。
已有成功分支的正文必须能够读取才能复用，不能仅根据摘要声称已经恢复结果。
成功摘要存在但 analysis 正文不可用时，报告材料缺失，不能静默重跑成功分支。
Workflow 在通知前始终持久化 `SessionRecord.output_frozen=true`，此后 final 内容冻结；不同正文覆盖返回冲突。该管理字段不受内容备份开关影响。final 正文未保存时本次可使用内存内容发送，但不可恢复补发。
相同内容的幂等保存允许返回成功，不创建同 output ID 的不同版本。
冻结后恢复只需要原快照、final 与回执即可补投，不强制重做采集或分析。
成功目标不自动重发；delivery_uncertain 不自动重试或补发，由 Workflow 保留诊断。
recoverable 根据记录阶段和材料完整性保守计算，Workflow 仍需验证具体续跑条件。
该字段不能仅以“有目录”或“有 LangGraph checkpoint”判断。

### 3.6 TTL、历史查询与并发

retention_days 有值时，每份内容从 written_at 计算 expires_at；元数据不随正文过期删除。
expire 跳过 created/running session，活动运行中的正文不会被清理任务删除。
终态 session 的过期内容读取即报告 expired，不等待清理进程实际删除文件。
清理时在 session 锁内重新检查当前状态，先持久化过期原因再移除正文文件。
删除失败保留过期标记与错误，后续清理可重试；过期内容不因此重新变为可恢复。
历史 Collector 通过 list/load 读取既有内容，最近次数、时间与 token 截取由 Collector 负责。
history 默认 `token_counter=utf8_bytes`，这是明确的保守预算，存档层不伪装为模型精确 token。
没有匹配 session 返回空列表；存在损坏或不可用内容则保留原因供上层执行策略。

## 4. 非功能性约束与验证

每个 session 使用一把异步锁，不同 session 可独立写入；创建和全局索引操作另行串行化。
过期清理、内容读取、状态更新和内容提交均使用同一 session 锁，避免互相穿透。
工作线程写入在完成或确认失败之前不释放锁；调用取消不得遗留越过后续更新的后台写入。
analysis 的完整视图由 Workflow 汇总；逐分支保存需先在汇总锁内合并，不允许旧副本覆盖新分支。
Store 不自行猜测业务层列表的合并语义，也不声称支持多个服务进程同时写同一目录。
验证覆盖重启读回、备份关闭/范围、哈希篡改、索引写故障、文件缺失和 TTL。
并发测试覆盖同 session 更新与清理竞争，恢复测试覆盖成功分支复用及冻结 final。
故障测试验证失败状态与成功材料同时保留，所有测试使用临时目录和可控时间。
十分钟稳定性由整体集成验收完成，本模块提供存档大小、记录数和缺失原因供报告使用。
