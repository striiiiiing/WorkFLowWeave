# 公共模型与协议任务

状态：已按最新 session 架构修订并验证通过。

依据：[总设计](../design.md)及相关模块 design.md及本次用户确认。contracts 为派生文档，不作为独立事实来源。旧任务与历史执行记录保留在基线 `4dfa8d0072fc16eda4f1c3da25bac36969327deb`；当前任务以设计提交 `97ebd68` 为基线，并纳入用户随后确认的 SessionStore/checkpointer 分工调整；旧“已完成”不代表符合新设计。

依赖：无。默认一个模块提交，只实现各模块共用的数据和窄接口。

- [x] 补齐 BackupPolicy、session 展示/正文可用性的数据约定；WorkflowDefinition 引用备份策略，SystemConfig 恢复全局运行容量设置。默认启用全阶段备份（proposal 默认保存）；默认容量沿用现有 RunCoordinator 的 4。保留天数如未指定则不自动过期，避免发明既有数据删除期限；显式期限须为正整数。
- [x] CollectionContext 增加可注入的 SessionReader 只读协议，供历史 Collector 调用；不得导入具体 Workflow/LangGraph 或序列化运行时依赖。为资源仓库、渠道注册视图提供必要协议，业务模块不依赖具体存储。
- [x] 保持 Pydantic 默认转换与未知字段拒绝，扩展内容严格 JSON-compatible；补齐投递结果的状态/attempts/error 一致性校验。
- [x] 同步派生 contracts 中受本次设计影响的职责、持久化和生命周期说明，不引入新的设计来源。AI 多模型配置与 600/5 默认值由 AI 模块任务统一实施，避免分拆迁移。
- [x] 定向模型/协议测试（60 秒硬超时）、lint、构建和序列化烟测；记录通过数量与命令。


## 实际实现与验证（2026-09-16）

- `models.py` 增加 `BackupPolicy`（快照/采集/分析/最终正文四范围，默认全开；retention_days 未指定不自动过期）、`WorkflowDefinition.backup`、`SystemConfig.max_concurrent_runs=4`、`SessionRecord`/`ArtifactInfo`/`PhaseContent`、`CollectionContext.session_reader` 和 `DeliveryResult` 一致性校验。状态包含设计要求的 `partial`；正文可用性与空正文区分。
- `protocols.py` 增加 `SessionReader`、`ResourceReader`/`ResourceStore` 和 `ChannelRegistryView` 窄协议。协议仅依赖模型和注入，不导入 Workflow/LangGraph。
- contracts/data-models.md 与 module-interfaces.md 已按当前总设计及模块 design.md 重写为派生说明；明确独立 SessionStore 业务内容、checkpointer 执行进度、JSON 资源、长期 channel 生命周期及业务 version 固定读取。
- 旧架构修订前验证（仅保留历史记录，不作为本次新结果）：`rtk proxy timeout 60s uv run pytest -q tests/test_contracts.py tests/test_shared_session_models.py` → 123 passed；`rtk proxy timeout 60s uv run pytest -q tests/test_run_store.py tests/test_workflow_recovery.py tests/test_workflow_integration.py` → 87 passed；`rtk proxy uv run ruff check src/workflowweave/models.py src/workflowweave/protocols.py tests/test_shared_session_models.py` → All checks passed。
- 旧架构修订前构建及烟测（同上）：`rtk proxy uv build` → 成功生成 `dist/workflowweave-0.1.0.tar.gz` 和 wheel；序列化烟测通过 `rtk proxy uv run python -` 验证 WorkflowDefinition、partial SessionRecord、含中文正文 PhaseContent 的 orjson/Pydantic round-trip 和 JSON Schema，运行时 reader 不出现在持久化 schema。

### 决策依据与默认值

- `proposal.md` 的目标与验收 5 要求默认保存采集输入、fan-out 及 fan-in 结果；总设计 §1.6 要求原配置快照受备份范围控制。因此选 snapshot/collection/analysis/final 四个正文范围，避免 notify/finish 对同一冻结输出再设置一套相互矛盾的开关；范围约束 SessionStore 正文及所有父子图、历史 checkpoint 中确需保留的同类副本，由后续 Workflow 任务执行。
- `on_failure=stop` 是本次实现选定的显式默认值，不冒充设计原文规定：proposal“备份失败按照配置停止或继续”和总设计 §5.1 要求报告不可完整恢复，默认停止避免在默认保存承诺失效后继续外部投递；用户可显式配置 continue，由 Workflow 标为 partial。retention_days=None 不发明删除期限；容量 4 沿用既有 RunCoordinator。
- SessionReader 使用正整数 version，依据用户最新确认的独立 SessionStore 业务存储和 Collection 设计的“一次查询固定所选历史版本”。SessionStore 每次新的逻辑写入递增版本，重放不递增；正文获取强制传入该版本，缺失不得自动改读最新内容。分页默认 100 沿用原 WorkflowService.list_sessions，时间过滤以 created_at 为包含边界，同时间按 session_id 排序以保证确定性。
- 本模块只提供公共表示和协议；JSON 仓库替换、SessionView 实现与正文策略执行分别属于后续 Config/Workflow 任务，不能把当前模型测试视为它们已经落地。AI 多模型及 600/5 不在此次修改范围。

### 本次 session 分工修订

- 修订依据：用户明确要求 session 可读内容与 checkpointer 分开，业务节点向独立 SessionStore 幂等写入，可使用复用的参数化闭包节点供父图/子图调用；主代理同步对应 proposal/design。公共查询不反向依赖 checkpoint 结构。
- SessionRecord/PhaseContent 将 checkpoint_id 替换为正整数 version；SessionReader 参数同步替换。time 查询继续使用 created_at 包含边界。SessionView 读取 SessionStore；公共协议仅保留只读访问，不公开 SessionStore 写入接口，内部写入由 Workflow 任务实现。
- 新增正整数边界、Pydantic 数字字符串转换、旧 checkpoint_id 拒绝测试；保留原备份策略、容量和投递结果校验。
- 本次重新验证：`rtk proxy timeout 60s uv run pytest -q tests/test_contracts.py tests/test_shared_session_models.py` → **134 passed in 0.81s**；`rtk proxy uv run ruff check src/workflowweave/models.py src/workflowweave/protocols.py tests/test_shared_session_models.py` → **All checks passed**；`rtk proxy uv build` → sdist 和 wheel 均构建成功。
- 本次烟测：`rtk proxy uv run python -` → WorkflowDefinition、version=2 的 partial SessionRecord 和中文 PhaseContent 均通过 orjson/Pydantic 往返；两种 session 模型 JSON Schema 的 version 为 integer 且 exclusiveMinimum=0、不再包含 checkpoint_id；SessionReader 仅有三个查询方法。`rtk proxy git diff --check` 通过。
- 已对照本次更新的总设计 §1.6、§5.4 与 Workflow“可复用、幂等的存档节点”段落复查派生说明：业务版本对应设计中的 version；写入节点、原子事务、重放幂等及版本递增由后续 Workflow 实现，本次模型测试不冒充存储行为验证。
