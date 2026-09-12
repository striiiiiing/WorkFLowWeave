# 接口契约：数据模型

对应 [总体设计 §4.1](../design.md#41-数据模型)。本文完整列出公共配置、执行结果、运行记录和接口辅助对象的字段。模型表达交换数据的含义，Python 仅用作伪代码记法，不要求采用特定基类、校验库或存储布局。

没有赋值的字段表示声明，不表示必须由用户填写；默认值和可空含义写在中文注释中。集合由每个对象独立持有。所有正文与扩展数据必须能表示为 JSON 值，运行时依赖和回调不进入配置或存档。

## 1. 基础类型与共同约束

```python
from datetime import datetime
from typing import Literal

ID = str                         # 1–80 位 ASCII 字母、数字、下划线或短横线；不是任意路径
EnvironmentName = str            # 环境变量名称，仅保存凭据引用
UTCDateTime = datetime            # 带时区的 UTC 时间；对外表示为 ISO 8601
Seconds = float                  # 正的有限秒数，不接受布尔值或数字字符串
JSONValue = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject = dict[str, JSONValue]  # JSON 对象；数值必须有限
JSONSchema = JSONObject           # 对扩展字段的结构化约束描述

ResourceKind = Literal["sources", "setters", "ai", "channels", "workflows"]
SaveMode = Literal["create", "replace", "upsert"]  # 仅创建、仅替换、存在则替换否则创建
SourcePolicy = Literal["stop", "skip"]            # 停止运行或跳过当前来源
ContinuePolicy = Literal["stop", "continue"]      # 停止下游或按允许范围继续
ArtifactName = Literal["snapshot", "collection", "analysis", "final"]
WorkflowStage = Literal["collect", "analyze", "aggregate", "notify", "finish"]

CollectionStatus = Literal["success", "empty", "filtered_empty", "missing", "failed", "timeout"]
AnalysisStatus = Literal["success", "failed", "timeout", "cancelled"]
DeliveryStatus = Literal["success", "failed", "timeout", "skipped"]
SessionStatus = Literal["created", "running", "completed", "partial", "failed", "cancelled", "interrupted"]
MissingReason = Literal["disabled", "out_of_scope", "not_created", "missing", "expired", "corrupt", "write_failed"]
```

公共输入拒绝未知字段，数值和开关不进行有歧义的隐式类型转换。`options`、`setters`、`model_options` 是显式扩展边界，内部字段由所属业务模块声明和校验；新增插件参数不等于允许任意顶层字段。

## 2. 配置资源

### 2.1 系统配置

```python
class SystemConfig:
    data_dir: str                # 资源及存档的根位置；默认 data
    plugin_dir: str              # 插件发现的根位置；默认 plugins
    host: str                    # 服务监听地址；默认 127.0.0.1
    port: int                    # 服务监听端口，1–65535；默认 8000
    max_concurrent_runs: int     # 同时活动的运行上限，至少 1；默认 4
    log_file: str | None         # 可选日志输出位置；None 不表示禁止诊断日志
    master_key_env: EnvironmentName # 主密钥环境变量名；默认 LOGAGENT_MASTER_KEY
    master_key_file: str          # 主密钥文件位置；默认 master.key
```

系统相对路径以系统配置文件所在位置为基准。来源和插件自己的路径含义必须由其能力声明解释，不能仅凭字段叫 `path` 就统一改写。运行快照应固定执行所需的有效位置，避免工作目录改变其含义。

### 2.2 来源与 Setter 模板

```python
class SourceConfig:
    id: ID                          # 数据源实例 ID，同一种 Collector 可以有多个实例
    collector: ID                   # Collector 能力名称；运行时不可用按 on_missing 处理
    options: JSONObject             # 连接、范围等来源选项；默认空对象
    setters: JSONObject             # 实例指定的字段、过滤、排序、分组等设置；默认空对象
    template: ID | None             # 引用 SetterTemplate；默认 None
    timeout: Seconds                # 单来源整体执行时限；默认 30 秒
    on_error: SourcePolicy          # failed/timeout 的处理；默认 stop
    on_missing: SourcePolicy        # Collector 缺失/加载失败、来源或必要历史内容缺失的处理；默认 stop
    on_empty: SourcePolicy          # 原始范围无记录的处理；默认 skip
    on_filtered_empty: SourcePolicy # 原始有记录但处理后无内容的处理；默认 skip

class SetterTemplate:
    id: ID                          # 可复用模板 ID
    collector: ID                   # 所属 Collector，必须与使用者相同
    setters: JSONObject             # 模板提供的 Setter 值；默认空对象
```

展开时先复制模板，再以实例显式给出的同名键覆盖。显式空列表也属于覆盖，其他键保留；不隐式深度合并同名复杂值。最终设置仍须满足 Collector 的能力声明，模板不授予额外能力。

### 2.3 AI 配置

```python
class AIConfig:
    id: ID                          # 可复用 AI 配置 ID
    provider: ID                    # 已支持的提供方；首版 mock/http，默认 mock
    model: str                      # 非空模型名称；默认 mock
    base_url: str | None            # 提供方访问地址；离线模式可为空
    api_key: Credential | None      # 环境变量引用或主密钥保护的密文；默认 None
    system_prompt: str              # 独立系统提示词；默认空字符串
    model_options: JSONObject       # 经提供方验证的模型参数；默认空对象
    timeout: Seconds                # 本次分析总时限，含所有尝试和重试等待；默认 60 秒
    retries: int                    # 首次失败后的额外尝试上限，非负；默认 0
```

顶层和模型扩展参数都拒绝 `temperature`、`top_k`。扩展参数不得覆盖服务管理的消息、模型标识、认证、地址或执行预算，仅接收本期声明支持的模型参数。timeout 和 retries 可通过 JSON 配置导入或 AI 资源 API 保存；分支与汇总引用相应 AIConfig，不提供 Workflow 或 AnalysisTask 层的覆盖值。最多尝试 `1 + retries` 次，总时限不随重试重置，耗尽后返回 timeout。凭据保存和恢复遵循 §2.5。

### 2.4 Channel 配置

```python
class ChannelConfig:
    id: ID                          # 具体通知目标的实例 ID
    channel: ID                     # 已注册的 Channel 类型名称
    options: JSONObject             # 路径、收件人、连接与 Credential 等；由类型校验
    timeout: Seconds                # 单次投递尝试时限；默认 30 秒
    retries: int                    # 首次失败后的额外尝试上限，非负；默认 0
    enabled: bool                   # 是否允许投递；默认 True
```

目标地址由配置确定，通知正文不能修改目标。邮件等插件的凭据字段使用 §2.5 的 Credential，由配置模块按需解析，`options` 不能绕过凭据管理要求。未知插件的选项字段以能力 schema 为准，不在公共模型中猜测或穷举。

### 2.5 受保护凭据

```python
class EnvironmentCredential:
    kind: Literal["env"]           # 环境变量引用
    name: EnvironmentName          # 保存变量名，不保存解析后的值

class EncryptedCredential:
    kind: Literal["encrypted"]     # 主密钥保护的凭据
    format_version: int            # 密文封套格式版本；首版为 1
    key_id: str                    # 加密使用的主密钥标识，不包含密钥本身
    ciphertext: str                # 认证加密封套，含算法标识、nonce、密文及认证标签

Credential = EnvironmentCredential | EncryptedCredential
```

需要持久化的凭据通过配置模块的 `protect` 能力加密，JSON 导入、资源 API、插件配置和快照仅接受环境变量引用或加密后的 Credential，不保存明文。运行时 `resolve` 按需读取环境变量或解密，解析值仅交给实际调用模块，不进入资源返回值、日志、错误响应或存档。

主密钥优先读取 `master_key_env` 指定的环境变量，变量未设置时读取 `master_key_file`；已提供的密钥格式错误或文件不可读时明确报错，不静默切换到新密钥。仅在首次初始化、两处都不存在主密钥且没有既有密文时生成并安全写入指定文件。存在既有密文时必须恢复原主密钥，无法确认是否存在密文时不自动生成。密文损坏、密钥不匹配或认证失败均报错，不覆盖密文。

快照固定环境变量引用或加密封套，不保留解密值；恢复依赖相应环境变量或原主密钥。凭据不可用时报告明确原因，不能改用最新资源中的凭据。备份迁移需同时保留原密文及独立保管的原主密钥。运行时日志脱敏独立于存储加密。

## 3. Workflow 配置

```python
class AnalysisTask:
    id: ID                          # 本 Workflow 内唯一的分支 ID
    ai: ID                          # 引用 AIConfig 的 ID
    prompt: str                     # 该任务的用户提示词；默认 {input}

class FanInConfig:
    order: list[str]                # 分支 ID 和至多一个 $input 的顺序；空列表采用全部分支声明顺序
    separator: str                  # 汇聚片段间分隔符；默认两个换行
    ai: ID | None                   # 可选汇总分析的 AI 配置；None 表示只编排文本
    prompt: str                     # 汇总分析使用的用户提示词；默认 {input}
    mark_incomplete: bool           # 是否在正文说明缺失分支；默认 True

class BackupPolicy:
    enabled: bool                   # 是否保存阶段正文；默认 True，不控制管理记录
    stages: list[ArtifactName]      # 保存范围；默认包含四个阶段，不重复
    on_failure: ContinuePolicy      # 正文保存失败后的策略；默认 stop
    retention_days: float | None    # 正的有限保留天数，允许小数；None 表示不按天过期

class WorkflowDefinition:
    id: ID                          # Workflow 资源 ID
    name: str                       # 展示名称；默认空字符串
    sources: list[ID]               # 有序来源实例 ID，至少一个且不重复
    analyses: list[AnalysisTask]    # 有序分析任务，至少一个且任务 ID 不重复
    fan_in: FanInConfig | None      # 可选汇聚配置；None 表示成功分支分别输出
    channels: list[ID]              # 有序通知目标 ID，不重复；可为空
    input_separator: str            # 来源文本之间的分隔符；默认两个换行
    include_counts: bool            # 是否附带各来源处理后计数及状态；默认 False
    collection_concurrency: int     # 同一运行的来源并发上限，至少 1；默认 4
    analysis_concurrency: int       # 同一运行的分析并发上限，至少 1；默认 4
    on_all_empty: SourcePolicy      # 全部来源无有效内容时 stop 或 skip；默认 stop
    analysis_failure: ContinuePolicy # 分支失败后是否允许下游继续；默认 continue
    send_partial: bool              # 是否允许发送部分成功结果；默认 True
    backup: BackupPolicy            # 本次运行的正文备份策略；默认使用 BackupPolicy 默认值
    interval_seconds: Seconds | None # 可选定时间隔；None 表示没有内置定时触发
    enabled: bool                   # 是否允许新的手动/定时触发；默认 True
```

`fan_in.order` 只能引用当前 Workflow 分支，不能重复；`$input` 代表完整共享输入，不能拆分移动。关闭正文标记不抹去结构化的失败事实。所有 fan-out 分支接收相同共享输入，来源子集与 Agent 模式属于后续版本。

```python
class WorkflowSnapshot:
    workflow: WorkflowDefinition   # 本次确定的完整 Workflow 定义
    sources: dict[ID, SourceConfig] # 引用来源的独立副本，Setter 已展开
    ai: dict[ID, AIConfig]          # 分支和可选汇总引用的 AI 配置副本
    channels: dict[ID, ChannelConfig] # 通知目标配置副本
    created_at: UTCDateTime         # 生成该一致配置视图的时间
```

映射必须恰好覆盖 Workflow 引用，键与对象 ID 一致。映射用于定位资源，顺序仍由 Workflow 列表决定。运行及恢复不得用最新资源替换快照；快照独立于资源和调用方返回对象的后续修改。

## 4. 错误与执行结果

### 4.1 统一错误

```python
class ErrorInfo:
    code: str                      # 稳定、可识别的错误类别
    message: str                   # 简洁的中文或其他可读说明
    details: JSONObject            # 脱敏字段路径、缺失原因和诊断信息；默认空对象

class ValidationIssue:
    path: list[str | int]          # 字段路径，如 ["analyses", 0, "ai"]
    reason: str                    # 可修正原因，不回显秘密或整份输入

class ErrorResponse:
    error: ErrorInfo               # 外部错误响应的统一封套
```

校验错误可在 `details.errors` 中放入 `ValidationIssue` 列表。执行失败作为结果返回；无效调用、状态冲突和基础设施不可用通过同一错误结构报告。错误机制可以由实现选择，调用方不能依赖内部异常类或堆栈。

### 4.2 采集结果

```python
class CollectorOutput:
    status: CollectionStatus       # 真实采集状态
    items: list[JSONObject]        # 可消费的处理后记录；默认空列表
    text: str                      # 对应可消费文本；默认空字符串
    count: int                     # 过滤处理后的有效内容数量，非负；单位由插件声明
    error: ErrorInfo | None        # 失败、超时或缺失原因；正常空与成功为 None
    metadata: JSONObject           # 计数方法、历史截取事实等诊断；默认空对象

class CollectionResult(CollectorOutput):
    source_id: ID                  # Manager 补充的来源实例 ID；其余字段与插件输出一致
```

| 状态 | 数据含义 |
| --- | --- |
| `success` | 存在可消费内容，文本不只含空白。 |
| `empty` | 插件确认原始范围没有记录，count 为零。 |
| `filtered_empty` | 插件确认过滤或内容投影后无内容，count 为零；不返回过滤前数量。 |
| `missing` | Collector 不存在或加载失败、指定来源或必要历史正文不存在、未保存或已过期。 |
| `failed` | 来源异常、权限或结构错误、正文损坏等；错误中保留原因。 |
| `timeout` | 本来源整体时限耗尽，不把未完成数据作为成功输入。 |

只使用处理后 count 进行编排和展示，不采集或推算过滤前数量。empty 与 filtered_empty 由插件状态区分；失败、超时或缺失不能根据 count 为零改判为正常空，未完成的内容不作为成功输入。

### 4.3 分析结果和投递回执

```python
class AnalysisResult:
    task_id: ID                    # 分支 ID；汇总分析有独立任务标识
    status: AnalysisStatus         # 分析状态：success/failed/timeout/cancelled
    text: str                      # 成功分析正文；失败不得伪造替代结果
    error: ErrorInfo | None        # 失败原因；成功时为 None
    usage: JSONObject              # 提供方可用的用量统计；未提供时为空，不编造消耗
    elapsed_ms: float              # 本次分析耗时，非负有限毫秒数

class Notification:
    session_id: ID                 # 所属运行 ID
    output_id: ID                  # 该 session 内稳定且唯一的输出 ID
    title: str                     # 通知标题；默认空字符串
    text: str                      # Workflow 已确定的待发送正文
    metadata: JSONObject           # Workflow、任务、阶段、不完整性等关联信息

class DeliveryResult:
    channel_id: ID                 # 本条回执对应的目标实例 ID
    output_id: ID                  # 本条回执对应的输出 ID
    status: DeliveryStatus         # 投递状态：success/failed/timeout/skipped
    attempts: int                  # 实际开始的尝试次数，非负；禁用目标为 0
    error: ErrorInfo | None        # 平台错误或不确定性；成功/跳过时为 None
```

一个 session 内以 `(output_id, channel_id)` 唯一标识投递事实。`delivery_uncertain` 不是第五种投递状态，它由 `error.details.delivery_uncertain = True` 表达：可能已接收，不自动重试或补发。SMTP 成功表示服务器接受请求，不表示收件人已经阅读。

## 5. 运行记录与阶段内容

```python
class ArtifactInfo:
    sha256: str                    # 保存内容的完整性摘要，64 位小写十六进制
    size: int                      # 保存内容的字节数，非负
    written_at: UTCDateTime         # 正文成功保存时间
    expires_at: UTCDateTime | None  # 可选过期时间；None 表示没有按时间过期

class SessionRecord:
    id: ID                         # 本次运行 ID；恢复沿用该 ID
    workflow_id: ID                # 所属 Workflow ID
    status: SessionStatus          # 当前运行状态；初始 created
    created_at: UTCDateTime         # 建立运行的时间，恢复不重置
    updated_at: UTCDateTime         # 最近一次记录更新时间
    stage: WorkflowStage           # 当前或停止的业务阶段；初始 collect
    source_statuses: dict[ID, CollectionStatus] # 来源实例到真实状态的映射
    analysis_statuses: dict[ID, AnalysisStatus] # fan-out 分支到真实状态的映射
    deliveries: list[DeliveryResult] # 各输出/目标的已记录回执
    errors: list[ErrorInfo]         # 已发生错误的诊断历史，不包含阶段正文
    artifacts: dict[ArtifactName, ArtifactInfo] # 已保存阶段的内容索引
    recoverable: bool              # 基于状态和材料的保守恢复提示；初始 False
    missing_artifacts: dict[ArtifactName, MissingReason] # 不可用阶段及原因
    output_frozen: bool            # 是否进入不可改写的最终输出边界；初始 False

class CollectionArtifact:
    shared_input: str              # 当时编排好的完整共享输入
    results: list[CollectionResult] # 按来源声明顺序保存的结果，保留失败事实

class AnalysisArtifact:
    order: list[ID]                # fan-out 的声明顺序
    results: list[AnalysisResult]  # 已有分支结果，可增量保存成功和失败项

class FinalArtifact:
    outputs: list[Notification]    # 有序、稳定输出 ID 及确定正文
    fan_in: AnalysisResult | None  # 可选汇总分析结果；纯拼接或关闭汇总时为空

ArtifactContent = WorkflowSnapshot | CollectionArtifact | AnalysisArtifact | FinalArtifact

class ArtifactAvailability:
    available: list[ArtifactName]  # 当前可核验、可读取的阶段名称
    missing_artifacts: dict[ArtifactName, MissingReason] # 每个不可用阶段的原因
    recoverable: bool              # 与 SessionRecord 相同的保守判断语义

class ExpirationReport:
    sessions: int                  # 本次处理的运行记录数量
    artifacts: int                 # 本次实际清除的过期正文数量
    errors: list[JSONObject]       # 清除失败的脱敏原因，便于后续重试
```

`snapshot` 的正文直接使用 `WorkflowSnapshot`。`analysis.results` 只引用 `order` 中的任务且不重复；`final.outputs` 的输出 ID 不重复且属于当前 session。管理记录不复制正文，关闭备份后不能把正文藏入 `errors` 或 `metadata` 来假装支持恢复。

为保持既有存档可识别，存档封套的逻辑字段如下；它是存档内部交换格式，公共 `get()` 返回 `SessionRecord`，不直接暴露封套。这一约定不指定文件名或物理存储结构。

```python
class SessionArchiveEnvelope:
    format_version: int            # 存档格式版本；既有契约为 1
    backup: BackupPolicy           # 本 session 的正文保存和过期策略
    record: SessionRecord          # 运行管理记录
    snapshot_sha256: str            # 原配置快照的摘要，用于识别不当替换
```

| session 状态 | 语义 |
| --- | --- |
| `created` | 已建档且被受控执行入口接管，等待运行。 |
| `running` | 已开始推进阶段。 |
| `completed` | 必要阶段成功，或按合法全空跳过策略正常结束。 |
| `partial` | 保留可用结果或允许继续的运行事实，同时存在来源、分析、投递或备份降级。 |
| `failed` | 停止策略触发、必要阶段失败或没有可用分析结果。 |
| `cancelled` | 取消已生效，后续阶段不再启动。 |
| `interrupted` | 生命周期检查发现先前运行未正常结束。 |

## 6. 能力描述和上下文

下列辅助对象补齐发现和上下文接口的语义返回形状；不表示这些类型已经实现。插件的专属选项由 `options_schema`、`setters_schema` 描述，插件自己的每个可配置字段都必须在 schema 中有类型和说明。

```python
class CapabilityDescription:
    name: ID                       # 注册能力的唯一名称
    description: str               # 面向使用者的能力说明
    plugin: str                    # 所属插件标识，不暴露任意宿主路径
    capabilities: list[str]        # 如 collection、notification；只列真实支持项
    options_schema: JSONSchema     # 该类型实例选项的全部字段约束
    setters_schema: JSONSchema | None # Collector Setter 约束；不适用时为空
    fields: list[str]              # 可选择的来源字段；不适用时为空
    count_unit: str | None         # 计数单位，例如记录数；不适用时为空

class DiscoveryReport:
    registered: list[CapabilityDescription] # 已生效的有效声明
    errors: list[ErrorInfo]         # 逐插件隔离的发现错误

class ExecutionContext:
    workflow_id: ID | None         # 可选关联 Workflow；独立 AI 调用可为空
    session_id: ID | None          # 可选关联运行；不要求 AI 绑定 Workflow
    stage: WorkflowStage | None    # 可选关联阶段

class CollectionContext:
    workflow_id: ID                # 当前 Workflow 标识
    session_id: ID                 # 当前运行标识
    archive: "ArchiveReader"       # 注入的只读存档能力，不允许由此触发历史运行
    log_path: str | None           # 已确定的工具日志来源位置
```

`ArchiveReader` 在 [模块接口](./module-interfaces.md) 中定义。执行上下文中的依赖引用只供当前调用使用，不成为持久化数据的一部分。

## 7. 健康结果

```python
class ComponentHealth:
    component: str                 # 模块或可选插件标识
    status: Literal["available", "degraded", "unavailable", "unknown"] # 最近可知状态
    required: bool                 # 是否为服务接受运行所必需
    error: ErrorInfo | None        # 脱敏诊断；无错误时为空
    checked_at: UTCDateTime | None # 最近检查时间；尚未检查时为空

class HealthReport:
    status: Literal["ready", "degraded", "unavailable"] # 汇总服务状态
    accepting_runs: bool           # 生命周期和必要依赖是否允许接收新运行
    checked_at: UTCDateTime         # 汇总状态的时间
    components: list[ComponentHealth] # 各组件的可用范围与原因
```

服务可降级并接收运行；已保存 Workflow 引用不可用 Collector 时，由采集阶段返回 missing 并按 on_missing 处理。未知远端状态不等于已验证连通；健康查询不隐式采集数据、调用付费模型或发送通知。具体健康规则见 [总体设计 §5.3](../design.md#53-可运维设计)。
