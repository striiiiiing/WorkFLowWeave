元信息
- 关联规范：[总设计](../../design.md)、[存档模块设计](./design.md)、[数据模型 §4–5](../../contracts/data-models.md)、[模块接口 §6](../../contracts/module-interfaces.md)。
- 任务总数：7。
- 预计执行时间：约 7.5 小时人工开发时间；单任务 45–90 分钟，独立任务可并行。

执行范围：Task 1–3 是本轮 history Collector 的最小前置读能力；Task 4–7 是后续完整存档模块任务。Mock/logs 不依赖存档落盘实现。以下保留原任务计划，实际完成范围与验证见文末执行记录。

依赖执行：公共契约 → Task 1 → Task 2 → Task 3。Task 4 在 Task 2 后可与 Task 3 并行；Task 5 等待 Task 3、Task 4，之后执行 Task 6、Task 7。存档模块不依赖 Workflow 的执行器，仅接受契约对象。

# Task 1: 建立存档模型与只读边界

描述：本轮 collection 前置，预计 45 分钟。实现读取所需的运行记录、封套、阶段正文及错误分类，并向 history 暴露只读 ArchiveReader 协议。

输入：contracts.SessionRecord、SessionArchiveEnvelope、ArtifactInfo、ArtifactAvailability 及四种 ArtifactContent 的字段规范。

输出：archive 的封套解析和阶段类型映射、archive.ArchiveReader 协议、缺失/损坏/基础设施错误的统一语义。

依赖：公共 ID、UTCDateTime、JSON、状态、BackupPolicy 和 ErrorInfo 契约。

验收标准：
- 严格校验 ID、UTC 时间、状态、版本、摘要格式和有限数值；不接受路径形式 ID 或未知字段。
- artifact 名称与 snapshot/collection/analysis/final 正文类型一一对应，运行时依赖不能进入可序列化正文。
- ArchiveReader 只暴露 get/list/load_artifact/availability，不包含创建、更新、恢复、采集或触发运行入口。
- missing/expired/disabled/out_of_scope 与 corrupt/write_failed 可被调用方区分，不通过空正文混淆真实原因。

# Task 2: 实现只读记录查询和稳定排序

描述：本轮 collection 前置，预计 60 分钟。读取既有管理封套，提供 history 所需的 Workflow 过滤与确定性列表；get/list 不提前读取所有正文，也不写入或修复状态，完整正文检查由 load_artifact/availability 完成。

输入：受控 sessions 根目录、session ID、可选 workflow_id 和 limit。

输出：archive.ArchiveReader.get/list 的文件实现，返回独立 contracts.SessionRecord。

依赖：Task 1。

验收标准：
- get 校验封套后仅返回 record；记录不存在与记录损坏分别报告，损坏文件不能伪装成不存在。
- list 按 created_at 倒序、同时间按 ID 倒序排列，workflow_id 精确过滤；内部 limit=None 返回所有匹配记录。
- 修改返回对象不改变磁盘或后续查询结果；查询 created/running 记录不会隐式标记 interrupted。
- 文件路径仅由合法 ID 与固定文件名构造，无法通过参数访问 sessions 根目录外文件。
- 为 history 提供终态和当前 session 信息，但不替 history 选择次数、时间范围或内容预算。

# Task 3: 实现可信正文读取与可用性判定

描述：本轮 collection 前置，预计 90 分钟。验证正文索引、策略、过期、大小、摘要、版本及结构，使 history 只读取可信历史内容。

输入：Task 2 的封套、固定 artifact 名称、正文文件及当前 UTC 时间。

输出：archive.ArchiveReader.load_artifact/availability；可供 history 使用的 CollectionArtifact、AnalysisArtifact、FinalArtifact 及完整缺失原因。

依赖：Task 2；公共阶段正文契约。

验收标准：
- 先检查备份策略和成功索引，再验证文件大小、sha256、版本和正文结构；无索引的孤立文件不得被当作成功备份。
- disabled、out_of_scope、not_created、missing、expired、corrupt、write_failed 分别返回对应语义；损坏正文不能返回成功内容。
- 校验 analysis.order 与结果任务归属及唯一性，final 输出归属与输出 ID 唯一性；返回正文对象与内部缓存/状态隔离。
- availability 基于可信材料保守判断：冻结后可凭 snapshot/final 和回执判断材料范围，冻结前不把缺失采集或已有成功分支正文当作可恢复。
- history 的文件集成用例覆盖正常 collection/analysis/final、备份关闭、正文缺失、过期及摘要损坏，且不触发写入或旧 Workflow。

# Task 4: 实现管理记录创建与合并更新

描述：后续完整存档任务，预计 60 分钟。建立每 session 锁和原子管理封套提交，记录创建、阶段状态、错误和投递事实。

输入：WorkflowSnapshot、BackupPolicy、workflow_id，以及允许更新的管理字段增量。

输出：archive.ArchiveStore.create/update，包含 snapshot_sha256 的管理封套。

依赖：Task 2；contracts.WorkflowSnapshot、contracts.DeliveryResult；不依赖 Workflow 执行器。

验收标准：
- create 要求 workflow_id 与快照一致，先落盘管理封套；关闭正文备份仍有完整管理记录和 snapshot_sha256。
- update 仅允许 status/stage/source_statuses/analysis_statuses/deliveries/errors/output_frozen，持有同 session 锁后基于最新记录合并。
- deliveries 按 (output_id, channel_id) 合并；成功或不确定事实不能被删除、降级或旧副本覆盖，output_frozen 不能撤销。
- 管理写入失败报告基础设施错误；临时文件及原子替换失败后不把候选状态报告为已提交。

# Task 5: 实现正文提交、增量分析和冻结约束

描述：后续完整存档任务，预计 90 分钟。以与读取共享的 session 锁提交正文及索引，并落实快照不可替换、最终输出冻结和写入失败语义。

输入：session ID、ArtifactName、符合归属约束的 ArtifactContent 和当前备份策略。

输出：archive.ArchiveStore.save_artifact；create 的按策略快照正文保存，以及可信内容索引。

依赖：Task 3、Task 4。

验收标准：
- 成功按“临时正文 → 大小和摘要 → 正式正文 → 管理索引”提交，读者不观察同进程的中间状态；未提交正文不进入成功索引。
- 备份关闭或范围排除返回 False；真实 I/O 失败报错并尽可能记录 write_failed，不能用 False 隐藏故障。
- snapshot 始终不可替换；冻结前 analysis 允许合法增量更新，保持声明顺序及已有结果归属。
- 冻结后所有阶段只接受与既有可核验正文完全一致的幂等保存；正文缺失时拒绝重新生成或替换旧材料。
- 正文与索引之间故障后的读取报告不可用，不自动将孤立文件补记为成功；正文不得复制到 errors 或 metadata 绕过备份策略。

# Task 6: 实现显式中断标记和过期维护

描述：后续完整存档任务，预计 60 分钟。提供启动时中断检查与终态正文清理，保持管理记录和缺失原因。

输入：已有 session 封套、备份保留策略、当前时间及调用方提供的启动阶段条件。

输出：archive.ArchiveStore.mark_interrupted/expire、contracts.ExpirationReport 及临时文件清理能力。

依赖：Task 5；lifecycle 在新任务准入前调用 mark_interrupted 的约定，可用测试替身验证，不等待完整生命周期实现。

验收标准：
- mark_interrupted 只将启动遗留 created/running 标为 interrupted，不自动恢复或采集；普通 get/list 不执行该修改。
- expire 只处理终态 session 的过期正文，活动记录和正文保持可用；无保留期限的正文不按天删除。
- 清理保留管理记录和 expired 原因；删除失败保留脱敏诊断，ExpirationReport 仅统计实际成功清除的正文。
- 只有确认不属于活动提交的临时文件才可清理；重复维护可安全执行，不引入无所属后台任务。

# Task 7: 验证并发提交与历史读取一致性

描述：后续完整存档任务，预计 45 分钟。通过有意义的故障注入和并发读写案例验证完整存档的事实可信度及 history 消费边界。

输入：完成的 ArchiveStore、history Collector、临时存档目录及文件提交故障注入点。

输出：覆盖真实文件与索引边界的回归用例及可复现验证命令。

依赖：Task 5、Task 6；collection.HistoryCollector 或等价的 history 能力实现。

验收标准：
- 同一 session 并发状态/回执更新不丢失已成功事实；不同 session 可独立推进，不被全局写锁串行化。
- 注入正文替换后、索引提交前中断，重新打开存档后明确标记缺失/损坏，不虚报成功备份。
- history 在写入/维护并发场景下只获得完整可信正文或明确错误，不读取半段 JSON 或已过期材料。
- 冻结后补发材料可用性与冻结前分析材料可用性分别验证，缺失材料不会触发静默重采或重分析。

执行记录（2026-09-13）

- Task 1 → Task 2 → Task 3 已完成并在开始 history 实现前通过分支验收；Task 4–7 尚未执行。
- 产物：`src/logagent/archive/reader.py`、`src/logagent/archive/__init__.py`、`tests/test_archive.py`。公开 `ArchiveReader` 协议和 `FileArchiveReader(data_dir, *, max_record_bytes=1048576, max_artifact_bytes=16777216, clock=UTC_now)`，没有写入或恢复入口。
- 存储约定：`data_dir/sessions/<id>/record.json` 为版本 1 的 `SessionArchiveEnvelope`；四种 artifact 文件为原始 UTF-8 JSON 对象，索引及 snapshot_sha256 均按实际文件字节计算。读取不创建目录或修复文件，单文件有大小上限，阻塞 I/O 在线程中执行。
- 验证：开始 history 前，`uv run pytest -q tests/test_archive.py` 得到 65 passed；补充损坏根目录符号链接用例后，`uv run pytest -q tests/test_archive.py tests/test_history.py` 得到 124 passed（archive 66、history 58）。`uv run ruff check src/logagent/archive src/logagent/collection/history.py tests/test_archive.py tests/test_history.py` 通过。覆盖记录/正文严格解析、稳定列表、七种不可用原因、摘要/归属/过期、读取上限、路径/符号链接边界、线程 I/O 及冻结前后的材料判断。
- 交叉审查修复：只有最初打开 sessions 根目录不存在才返回空列表；读取途中记录或整个目录消失均报告 session_not_found。新增 3 个回归案例后，archive 69 项、history 58 项通过；最终全量回归在 Python 3.11.15 和 3.14.3 各通过 368 项。
