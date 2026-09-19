# 数据模型契约（设计派生说明）

依据[总设计](../design.md)、[Workflow](../modules/workflow/design.md)、[Collection](../modules/collection/design.md)及[配置设计](../modules/config/design.md)。并纳入用户本次确认的“SessionStore 保存可读内容、checkpointer 保存执行进度”调整。本文件不构成独立事实来源。配置使用 Pydantic 默认类型转换，拒绝未知字段并校验取值；扩展内容严格 JSON-compatible。运行时客户端、任务句柄、读取器和明文凭据不进入配置、结果或 checkpoint。

## 基础类型和配置

`ID` 为 1 至 80 个 ASCII 字母、数字、下划线或短横线。`JSONObject` 和 `JSONValue` 拒绝非 JSON 类型、非有限浮点数及 orjson 无法编码的数据。时间必须带时区，读入后统一为 UTC。

`SystemConfig` 包含 data_dir、plugin_dir、host、port、max_concurrent_runs、log_file、master_key_env 和 master_key_file。全局容量默认 4；日志路径只是标准 logging 输出配置，不是 Collection 自有数据库。

`SourceConfig` 描述来源、options、setters、template、timeout 和来源策略；`AIConfig` 描述模型请求配置；`ChannelConfig` 描述通知实例配置。AIConfig 以非空 `models: {模型名: JSON参数}` 映射作为模型选项的唯一来源，共享 provider/base_url/api_key/system_prompt/timeout/retries。模型名允许供应商路径，但不能为空或全为空白。默认 timeout=600 秒、retries=5，依据 AI design 的非流式长思考场景。旧 model/model_options 字段不再接受，旧配置须显式迁移，不能隐式猜选模型。

AnalysisTask 必填 model；FanInConfig 的 ai/model 同时提供或同时省略，省略表示纯拼接。WorkflowSnapshot 校验所有所选模型存在；资源更新若删除被引用模型，整个候选资源视图拒绝发布。

资源使用版本化 JSON 文件保存。Credential 仅允许环境变量引用或加密值；解析后的秘密只交给请求组件。

## Workflow 配置与快照

SourceOverride 包含 options、setters（默认空对象）、template（默认 None）；ChannelOverride 包含 options（默认空对象）。WorkflowDefinition 新增 source_overrides/channel_overrides（已引用 ID 的映射，默认空）。options_schema 顶层 x-logagent-workflow=true 标明调用字段；其余字段只在实例设置。WorkflowSnapshot.sources/channels 保存合并后的有效配置。PluginSettings 仅 enabled；插件通过 api.config_path 自行读取私有 JSON。

`WorkflowDefinition` 引用来源、分析任务、汇总、渠道和 `BackupPolicy`。后者的 enabled 总开关与 snapshot、collection、analysis、final 四个范围开关默认全部开启；分别控制原配置快照、采集输入、分析分支结果和冻结后的最终输出。notify/finish 中的最终正文仍服从 final，不能通过另一份 checkpoint 状态绕过范围限制。状态、错误、回执及可用性等管理信息不受正文开关控制。

retention_days 默认 None，表示不自动过期；显式天数须为正整数。on_failure 默认 stop；显式 continue 时须报告 write_failed 和备份降级。备份策略由 Workflow 模块应用到 SessionStore 的正文；checkpointer 内确需持久化的正文副本（含父图、子图、历史 checkpoint 与 pending writes）同样受范围限制。过期清理只处理终态 session 的正文，不能从另一份副本重新暴露已清理内容。

`WorkflowSnapshot` 包含 workflow、sources、ai、channels 和 created_at，从同一有效资源视图复制，映射恰好覆盖引用。后续配置修改不影响已受理运行；原快照按备份策略保存在 SessionStore；checkpointer 保存执行位置和恢复引用。恢复使用原版本快照，不得换成当前配置。

## 执行结果与 session 查询

`CollectorOutput` / `CollectionResult` 描述 success、empty、filtered_empty、missing、failed 或 timeout。成功必须有可消费文本和正数 count；非成功不能暴露未完成正文。`AnalysisResult` 描述 success、failed、timeout 或 cancelled。

`Notification` 包含 session_id、output_id、标题、正文和 metadata。`DeliveryResult` 成功时 attempts=1 且无错误；skipped 时 attempts=0 且无错误；failed/timeout 必须有错误，attempts 可为 0（尚未进入 send）或 1。每条通知最多调用一次 send；不确定投递通过 ErrorInfo 明确表示，不自动补发。

`SessionRecord` 是 SessionView 从独立 SessionStore 读取的业务数据，包含 workflow_id、session_id、version、状态、阶段、时间、错误、阶段可用性和 snapshot_availability。LangGraph 节点幂等维护 SessionStore；checkpointer 仅负责执行进度与恢复，SessionView 不解析 checkpoint。状态包括 created、running、completed、partial、failed、cancelled、interrupted；局部失败或备份降级表现为 partial，主动关闭备份本身不是业务失败。

`ArtifactInfo` 保存阶段、availability、可选字节数和错误；availability 为 available、pending、not_saved、expired、missing、corrupt 或 write_failed。`PhaseContent` 增加 session_id、version 与严格 JSON content；available 必须携带非 null 正文，其他状态不能携带正文。空字符串、空数组或空对象可以是有效已保存正文，与不可用状态不同。

version 是正整数，由 SessionStore 在每次新的逻辑写入时递增；幂等重放不增加版本。历史查询先选定 SessionRecord 版本，再按相同 version 读取内容；该版本已过期或不存在时明确返回不可用原因，不替换为最新版本。session_id 与 LangGraph thread_id 关联，列表每个 session 返回最新业务版本；业务版本不等同于 checkpoint ID。

错误统一使用 `ErrorInfo(code, message, details)`；details 不得包含秘密或完整敏感正文。

## 插件与调用上下文

`PluginManifest` 声明 id、version、kind、api_version 和 entry.backend；`CapabilityDescription` 声明能力及 JSON Schema；`DiscoveryReport` 返回注册项和诊断。

```python
@dataclass(frozen=True, slots=True)
class CollectionContext:
    workflow_id: ID
    session_id: ID
    log_path: str | None = None
    credentials: CredentialResolver | None = None
    session_reader: SessionReader | None = None
```

SessionReader 是运行时注入的只读协议，不序列化，也不向 Collector 暴露 Workflow 或 LangGraph 实现。缺少历史读取依赖时，历史 Collector 必须报告缺失能力。log_path 指向标准 logging 输出，Collection 不负责创建、轮转或保存日志。
