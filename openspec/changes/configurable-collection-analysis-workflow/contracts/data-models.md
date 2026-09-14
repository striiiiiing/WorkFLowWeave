# 数据模型契约

所有模型为严格 JSON-compatible 数据模型；运行时依赖只存在于调用上下文，不进入配置或结果序列化。系统不定义运行记录、存档、备份或恢复模型。

## 基础类型

`ID` 为 1 至 80 个 ASCII 字母、数字、下划线或短横线。`JSONObject` 和 `JSONValue` 必须可被 JSON 序列化。时间使用带时区的 UTC datetime。插件能力通过 `PluginManifest` 声明 `collector` 或 `channel`。

## 配置资源

`SystemConfig` 包含 `data_dir`、`plugin_dir`、`host`、`port`、可选 `log_file`、`master_key_env` 和 `master_key_file`。`log_file` 只是标准 Python `logging` 的输出配置，不是 Collection 的日志数据库。

`SourceConfig` 包含来源 ID、Collector 名称、options、setters、可选 template、timeout 及来源策略。`AIConfig` 包含 provider、model、提示词、模型选项、timeout、retries 和 Credential。`ChannelConfig` 包含 Channel 名称、options、timeout 和 enabled。`AnalysisTask`、`FanInConfig` 与 `WorkflowDefinition` 描述分析分支、汇总和执行顺序。

资源由配置模块以版本化 JSON 保存。Credential 只允许环境变量引用或加密值，解析后的秘密只交给实际调用模块，不进入日志、错误响应或快照。

## WorkflowSnapshot

```python
class WorkflowSnapshot:
    workflow: WorkflowDefinition
    sources: dict[ID, SourceConfig]
    ai: dict[ID, AIConfig]
    channels: dict[ID, ChannelConfig]
    created_at: UTCDateTime
```

快照从一次执行开始时的同一份有效资源视图深复制而来，映射必须恰好覆盖 workflow 引用。它只固定本次执行的配置，执行结束后不写入运行记录，也不作为下一次调用的恢复材料。资源后续修改不影响当前调用。

## 执行结果

`CollectorOutput` / `CollectionResult` 表示单来源的 success、empty、filtered_empty、missing、failed 或 timeout；成功必须有可消费文本和正数 count，失败不得携带未完成正文。

`AnalysisResult` 表示单个任务的 success、failed、timeout 或 cancelled。`Notification` 包含本次调用的 `session_id`、`output_id`、标题、正文和 metadata；`DeliveryResult` 包含 channel、output、状态、attempts 和错误。`CollectionArtifact`、`AnalysisArtifact`、`FinalArtifact` 只表示当前调用内存中的阶段值，不是持久化 artifact。

错误统一使用 `ErrorInfo(code, message, details)`；details 不得含秘密或完整敏感输入。

## 插件与上下文

`PluginManifest` 指定 id、version、kind、api_version 和 `entry.backend`。`CapabilityDescription` 描述注册能力及其 JSON Schema；`DiscoveryReport` 返回本次发现的注册项和诊断。

```python
@dataclass(frozen=True, slots=True)
class CollectionContext:
    workflow_id: ID
    session_id: ID
    log_path: str | None = None
    credentials: CredentialResolver | None = None
```

上下文只服务于当前调用。`session_id` 是关联字段，不代表可查询或可恢复的持久化会话。`log_path` 指向标准 logging handler 产生的日志输出；Collection 不负责创建、轮转或保存日志。
