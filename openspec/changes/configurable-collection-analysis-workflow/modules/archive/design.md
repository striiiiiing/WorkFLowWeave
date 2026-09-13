# 运行记录与存档模块设计

[总设计](../../design.md) · [接口契约](../../contracts/module-interfaces.md#6-运行记录与存档) · [模型](../../contracts/data-models.md#5-运行记录与阶段内容)

存档保存运行管理事实和策略允许的正文，向 API、history Collector 和 Workflow 返回可信材料。它不决定业务重跑策略。

## 结构与写入者

| 组件 | 职责 |
| --- | --- |
| SessionRepository | SessionRecord、备份策略和封套，维护状态、错误、投递及内容索引。 |
| ArtifactStore | snapshot/collection/analysis/final 四种 JSON 正文。 |
| IntegrityIndex | 正文摘要、size、版本及写入/过期时间；作为封套字段，不另设数据库。 |
| AvailabilityService | 判定可用阶段与缺失原因，返回保守 recoverable。 |
| RetentionService | 清理终态过期正文，保留记录及过期原因。 |

这些可以是 ArchiveStore 的内部函数。Workflow 是业务写入者；启动入口可标记 interrupted，维护入口可清理。API 和 history 只注入 ArchiveReader。

首版可按 data_dir/sessions/<session_id>/ 存储：record.json 保存 SessionArchiveEnvelope，其他四个固定名称文件保存相应 artifact。路径由经过校验的 ID 和枚举生成；外部只通过 session/artifact 名称访问，不直接接收文件路径。

## 提交顺序

create 先保存管理封套，按策略保存 snapshot；备份关闭时仍保留管理事实及 snapshot_sha256，不把快照正文藏入记录。管理记录失败报基础设施错误，正文失败标记 write_failed 后由 Workflow 处理 BackupPolicy。

update 在单 session 锁内读取最新记录、合并允许变更、原子替换 record.json，不用调用方旧副本覆盖全部状态。deliveries 以 `(output_id, channel_id)` 合并本次回执，保留成功/不确定事实；错误历史可追加脱敏原因，不保存正文。

save_artifact 验证正文结构、session/task 归属及冻结约束后，先写临时正文、计算摘要与大小、替换正式正文，再更新管理索引。读写使用同一 session 锁，读者不读取中间提交状态；进程崩溃造成文件与索引不一致时明确报告不可用，不自动承认孤立文件是成功备份。

analysis 允许在冻结前增量更新；snapshot 始终不可替换。output_frozen 设置后只接受与既有可核验正文相同的幂等保存，缺失正文不能重新生成冒充旧材料。备份开关/范围不允许写入时 save_artifact 返回 False；I/O 失败报错，不能同样返回 False 隐藏故障。

## 读取与恢复材料

load_artifact 先查看索引、策略、过期时间，再校验文件大小、sha256、封套版本及正文结构。只返回通过验证的独立对象。availability 不读取私有业务规则，只基于材料给出保守提示：

| 原因 | 解释 |
| --- | --- |
| disabled / out_of_scope | 用户关闭备份或未选择该阶段。 |
| not_created | 该阶段尚未产生正文。 |
| missing / expired | 原本需要的正文丢失或过期。 |
| corrupt / write_failed | 正文验证失败，或写入未成功提交。 |

冻结前的恢复通常需要 snapshot、collection 及已有成功 analysis；冻结后补发只需要完整 snapshot/final 和回执，不强求 collection/analysis 保留。最终是否有可安全执行的待办项由 WorkflowService 判定，recoverable 不是自动执行指令。

## 中断、保留与磁盘占用

mark_interrupted 仅在启动、接收新任务前检查遗留 created/running 记录，普通查询不改变状态。不会自动恢复旧运行。

expire 仅处理终态 session 的过期正文，并保留管理记录、索引中的过期原因。删除失败保留诊断，后续维护可重试；活动正文不会被清理。临时写入文件在确认不属于活动提交后清理，避免积累占用。日志正文不重复备份到 errors/metadata，避免绕过保留策略。

## 验证要点

覆盖写入与索引之间中断、摘要/版本不符、增量结果合并、冻结幂等写、成功回执不可降级、备份关闭/过期、活动运行不清理和查询无状态副作用。
