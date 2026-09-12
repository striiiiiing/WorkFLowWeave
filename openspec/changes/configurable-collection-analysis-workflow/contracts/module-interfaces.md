# 接口契约：模块对外能力

对应 [总体设计 §4.2](../design.md#42-模块接口定义)，所有数据类型见 [数据模型](./data-models.md)。这里的名称描述能力边界，Python 是伪代码，不要求实际代码采用同名类、特定框架、继承树或进程内调用方式。

`async` 表示调用可能等待 I/O 或任务完成，调用方应能等待并取消；它不规定内部是否使用线程、队列或执行图。失败统一使用 `ErrorInfo` 的语义，具体语言可采用异常或显式错误返回。方法体中的 `...` 只省略实现，不省略字段。

## 1. 共同调用规则

| 规则 | 对调用者的保证 |
| --- | --- |
| 校验与执行分离 | `validate` 不采集原始数据、不请求付费模型、不发送通知。校验通过不承诺远端永远在线。 |
| 输入与返回值隔离 | 被调用模块不修改调用方的配置或通知；读取返回独立视图。 |
| 原因可识别 | 无效输入、不存在、冲突、容量不足、基础设施不可用和执行失败有不同语义。 |
| 状态如实表达 | 正常空、过滤后空、失败、超时、取消和投递不确定性不能互相替代。 |
| 运行事实关联 | 结果携带来源、任务、输出或 session 标识，调用方能关联完整运行。 |
| 有界等待与取消 | 采集、模型和通知不无限等待；取消生效后不启动新的下游工作。 |

## 2. 配置与资源管理

**调用方：** 业务服务、交互入口、应用装配入口。系统和插件设置读取只负责取得并结构校验设置，插件能力的语义校验归所属模块。

```python
class ConfigurationReader:
    async def load_system(self, location: str) -> SystemConfig: ...
    async def load_plugin_config(self, location: str) -> JSONObject: ...

class CredentialManager:
    async def initialize(self, config: SystemConfig) -> None: ...
    async def protect(self, plaintext: str) -> EncryptedCredential: ...
    async def resolve(self, credential: Credential) -> str: ...

class ResourceStore:
    async def save(self, kind: ResourceKind, model: Resource,
                   *, mode: SaveMode = "upsert") -> Resource: ...
    async def get(self, kind: ResourceKind, id: ID) -> Resource: ...
    async def list(self, kind: ResourceKind) -> list[Resource]: ...
    async def delete(self, kind: ResourceKind, id: ID) -> None: ...
    async def resolve(self, definition: WorkflowDefinition) -> WorkflowSnapshot: ...
    async def snapshot(self, workflow_id: ID) -> WorkflowSnapshot: ...

# Resource 表示下列资源之一；kind 必须与其具体类型对应，返回值保持该类型。
Resource = SourceConfig | SetterTemplate | AIConfig | ChannelConfig | WorkflowDefinition
```

| 接口 | 语义与失败边界 |
| --- | --- |
| `load_system` | 返回合法系统配置和明确的路径含义；缺失或无效的必要配置阻止服务就绪。 |
| `load_plugin_config` | 可选插件设置不存在时返回空对象；无效或不可读时报告原因，由发现入口隔离该插件。 |
| `save` | `create` 拒绝已有 ID，`replace` 拒绝不存在 ID，`upsert` 允许两者。通过结构、引用及业务校验的变更完整生效，失败保留原有效配置。 |
| `get/list` | 返回独立资源视图；列表按 ID 稳定排序。损坏资源明确报错，不默认为不存在。 |
| `delete` | 被引用时返回冲突，不连带删除引用方。与并发保存协调，保证提交后的引用有效。 |
| `resolve` | 为尚未保存的定义装配完整快照，供业务验证；没有资源写入副作用。 |
| `snapshot` | 从一致资源视图取得已保存 Workflow 的完整配置；资源记录缺失或错配仍报告错误，但不重新验证插件可用性，Collector 缺失或加载失败不阻止生成快照。 |

Source/Setter 交由采集模块校验，AI 交由 AI 模块校验，Channel 交由网关校验；Workflow 保存由其服务统一组织。被引用资源的更新必须重新验证受影响关系，不能留下“单个资源合法、引用它的 Workflow 已无效”的状态。具体协调机制由实现选择。

`CredentialManager.initialize` 按数据模型 §2.5 的优先级读取主密钥，仅满足首次初始化条件时生成；已有密文缺少原主密钥时报告原因并保留密文。`protect` 返回认证加密封套，不保存或回显明文；供本地配置准备和受控导入流程使用，不新增返回明文的 HTTP 路由。`resolve` 仅向运行时调用模块返回解析值；环境变量缺失、密钥不可用或解密失败均明确报错。资源及存档只保存 Credential，诊断和日志独立脱敏。

资源保存成功后，新运行可取得新配置；已有 session 的快照保持不变。文件布局、缓存及一致性实现不属于本契约。

## 3. 数据采集

**调用方：** Workflow 调用管理入口；交互入口查询能力；可信插件通过扩展入口注册实现。

```python
class CollectorManager:
    def register(self, collector: "Collector") -> None: ...
    async def discover(self, location: str, plugin_config: JSONObject) -> DiscoveryReport: ...
    def describe(self) -> list[CapabilityDescription]: ...
    def validate(self, source: SourceConfig) -> None: ...
    async def collect(self, source: SourceConfig,
                      context: CollectionContext) -> CollectionResult: ...

class Collector:
    # 下列声明提供名称及可配置边界，不要求继承某个运行时父类。
    name: ID                        # 注册名称
    options_schema: JSONSchema      # 来源选项的完整约束
    setters_schema: JSONSchema      # 允许使用的 Setter 约束

    async def collect(self, options: JSONObject, setters: JSONObject,
                      context: CollectionContext) -> CollectorOutput: ...
```

`Collector.collect` 负责来源内部的字段选择、过滤、排序、分组、计数和格式化，返回包含处理后 items、text、count、状态及诊断的 CollectorOutput；计数方式和处理顺序由插件公开声明。只返回过滤处理后的数量，不返回或使用过滤前数量。Manager 校验返回结构、补充来源实例关联，形成统一 CollectionResult，不重复处理插件的记录。

`validate` 用于提交配置时检查 Collector、选项、已展开 Setter 和能力边界，不作为已保存 Workflow 触发时的重新校验门槛。运行时 Collector 未注册或加载失败，Manager 返回 missing 并保留发现错误；执行时参数或结构错误返回 failed。插件用 empty/filtered_empty 区分原本无数据和处理后无内容，无须返回过滤前数量。`collect` 返回事实，不执行 Workflow 的 stop/skip；跨来源排列和 on_missing/on_error 等策略由 Workflow 负责。

`discover` 使一个插件的有效声明整体可见；导入、配置或名称冲突使该插件的声明整体失败，其他插件继续可用。这里保证注册可见性，不承诺隔离插件代码的任意外部副作用。

内置来源包括 `mock`、`logs`、`history`。历史选择支持 Workflow、最近次数、时间和 token 预算，明确计数算法与 `truncate/error` 策略，只按完整记录截取；正常无匹配为 `empty`，必要内容缺失为 `missing`，损坏为 `failed`。日志读取有界，不能为取尾部日志无上限读取全部内容。

## 4. AI

**调用方：** Workflow 分支、可选汇总和后续 Agent。调用者显式提供任务和配置，不要求创建 Workflow session 才能调用 AI。

```python
class AIService:
    def validate(self, config: AIConfig) -> None: ...
    async def execute(self, config: AIConfig, prompt: str, input_text: str,
                      *, task_id: ID,
                      context: ExecutionContext | None = None) -> AnalysisResult: ...
```

`execute` 将每个字面 `{input}` 替换为完整输入；没有占位符时在提示词末尾附加输入。系统提示词和用户任务保持角色隔离，JSON 花括号等普通文本不能触发任意模板执行。

`execute` 只从 AIConfig 读取 timeout 和 retries，最多尝试 `1 + retries` 次；timeout 覆盖整次执行的所有请求和重试等待，到期返回 timeout，不因重试重置预算。只重试可重试且确认未成功的暂态失败；配置、认证及不可重试协议错误立即失败，取消后不启动新的请求或重试。Workflow 分支和可选汇总使用其引用的 AI 配置，无额外覆盖优先级。

Mock 和真实模型使用相同结果语义。配置错误在执行前报告；网络及模型协议故障保留明确原因，不能把错误响应当作成功分析文本。

## 5. Channel 网关

**调用方：** Workflow 提交确定的通知，装配入口管理实例生命周期，交互入口查询能力，可信插件提供平台适配。

```python
class ChannelManager:
    def register(self, channel: "ChannelType") -> None: ...
    async def discover(self, location: str, plugin_config: JSONObject) -> DiscoveryReport: ...
    def describe(self) -> list[CapabilityDescription]: ...
    def validate(self, config: ChannelConfig) -> None: ...
    async def start(self, configs: list[ChannelConfig]) -> None: ...
    async def stop(self) -> None: ...
    async def publish(self, configs: list[ChannelConfig],
                      notifications: list[Notification]) -> list[DeliveryResult]: ...

class ChannelType:
    name: ID                        # 平台类型注册名称
    capabilities: list[str]        # 真实支持的能力；首版目标需含 notification
    options_schema: JSONSchema     # 该平台实例配置的完整约束

class NotificationChannel:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def publish(self, notification: Notification) -> None: ...
```

类型声明与可发布的实例是不同角色，实例的具体构造方式由实现决定。平台发布成功后正常返回，失败提供结构化原因，由 Manager 统一形成回执。调用者不用解析 SMTP 或其他平台的私有异常。

`publish` 先按通知声明顺序，再按目标声明顺序处理。例如 `[A, B]` 发给 `[X, Y]`，顺序是 `A→X`、`A→Y`、`B→X`、`B→Y`。此顺序只约束同一批次，不承诺并发 session 的全局顺序。一个目标失败不抹去其他回执。

最多尝试 `1 + retries` 次，只重试确认未被接收的暂态失败；永久错误及 `delivery_uncertain` 不自动重试。禁用目标返回 `skipped/attempts=0`，不创建投递副作用。同一文件目标的多条消息保持完整边界。

Workflow 为及时记账，可以按相同顺序每次传入一条通知和一个目标，回执一返回便持久化。网关不读取存档，不自行安排 session 恢复。首版只有发送能力，接收和会话路由属于后续能力。

## 6. 运行记录与存档

**调用方：** Workflow 写入运行事实；API 和历史 Collector 只读；生命周期入口显式标记中断，维护入口执行过期清理。

```python
class ArchiveReader:
    async def get(self, session_id: ID) -> SessionRecord: ...
    async def list(self, workflow_id: ID | None = None,
                   limit: int | None = 100) -> list[SessionRecord]: ...
    async def load_artifact(self, session_id: ID,
                            name: ArtifactName) -> ArtifactContent: ...
    async def availability(self, session_id: ID) -> ArtifactAvailability: ...

class ArchiveStore:
    # 对外提供 ArchiveReader 的全部只读能力，以及下列写入/维护能力。
    async def create(self, workflow_id: ID, snapshot: WorkflowSnapshot,
                     backup: BackupPolicy) -> SessionRecord: ...
    async def update(self, session_id: ID, **changes: JSONValue) -> SessionRecord: ...
    async def save_artifact(self, session_id: ID, name: ArtifactName,
                            content: ArtifactContent) -> bool: ...
    async def mark_interrupted(self) -> list[SessionRecord]: ...
    async def expire(self) -> ExpirationReport: ...
```

| 能力 | 保证 |
| --- | --- |
| `create` | 建立新运行管理记录；快照必须与 Workflow ID 一致。正文备份失败保留已建立的事实，管理记录自身不可用则报基础设施错误。 |
| `get/list` | 返回独立记录，列表按创建时间倒序、同时间按 ID 倒序；内部 `limit=None` 表示不限量，外部查询仍须有界。普通查询不改变运行状态。 |
| `update` | 只更新声明允许的管理字段，合并当前记录的变更，不以旧完整副本覆盖其他更新。 |
| `save_artifact` | 名称与正文类型相符；成功返回 True，被备份开关或范围排除返回 False，尝试写入失败报告错误。只有已提交正文才能进入成功索引。 |
| `load_artifact` | 返回通过索引、完整性、版本与结构核验的正文；文件或内容碰巧存在不等于可信可用。 |
| `availability` | 区分关闭、范围排除、未生成、缺失、过期、损坏和写入失败，保守计算可恢复材料。 |
| `mark_interrupted` | 启动且尚未接收任务时检查先前遗留运行，标记中断；不自动恢复或重采，也不影响当前已接管的活动运行。 |
| `expire` | 按策略清除终态运行的过期正文，保留管理事实和过期原因；活动运行不被清理。 |

`update` 允许变更 `status/stage/source_statuses/analysis_statuses/deliveries/errors/output_frozen`，其余记录字段由存档管理。冻结标记不可撤销；进入通知和保存回执前先设置冻结。成功回执及不确定投递事实不能删除或降级。

快照不可替换；最终输出冻结后所有阶段只允许与既有可核验正文一致的幂等保存。缺失内容不能通过重新提交或重新分析伪装成原材料。跨记录和正文的故障必须可诊断，不要求具体物理事务技术，但不能报告未完成的提交为成功。

## 7. Workflow

**调用方：** API、定时触发入口及后续控制入口。业务入口共享规则，具体触发来源不改变配置和恢复语义。

```python
class WorkflowService:
    async def validate(self, definition: WorkflowDefinition) -> None: ...
    async def save(self, definition: WorkflowDefinition,
                   *, mode: SaveMode = "upsert") -> WorkflowDefinition: ...
    async def trigger(self, workflow_id: ID) -> SessionRecord: ...
    async def wait(self, session_id: ID) -> SessionRecord: ...
    async def resume(self, session_id: ID) -> SessionRecord: ...
    async def cancel(self, session_id: ID) -> SessionRecord: ...
    async def shutdown(self) -> None: ...
```

`save` 的创建/替换语义与 ResourceStore 相同，补充 `mode` 使 API 的 POST/PUT 存在性约束能在同一业务提交边界兑现。这个参数是本轮的契约澄清，不表示相应代码已经落地。

| 接口 | 前置条件与结果 |
| --- | --- |
| `validate/save` | 校验来源、展开模板、AI、目标、fan-in 顺序及策略；保存失败不发布半有效定义。 |
| `trigger` | Workflow 存在且启用，容量允许；固定快照并建档，返回已受理的 session。不能接受临时业务配置覆盖。 |
| `wait` | 等待一次运行结束并返回最新记录；取消等待不等于取消 Workflow。 |
| `resume` | 仅恢复有待办的 failed/partial/cancelled/interrupted 记录，保持原 ID、快照及创建时间；活动或已完成无待办记录拒绝恢复。 |
| `cancel` | 取消排队或运行中的工作，状态写回后返回；已取消时幂等，其余不可取消终态返回冲突。 |
| `shutdown` | 停止新准入，结束或取消活动工作，回收所属后台任务；可重复调用。 |

触发不重新校验插件可用性；已保存 Workflow 引用的 Collector 缺失或加载失败时，进入采集阶段，由 Manager 返回 missing，Workflow 按来源的 on_missing 停止或跳过并记录原因。新提交配置的校验规则仍由 validate/save 执行。

执行阶段为 `collect → analyze → aggregate → notify → finish`，是业务状态顺序，不要求特定图执行器。每完成阶段保存事实，分析分支结果可增量保存，最终排列仍采用配置顺序。

fan-out 使用同一份完整共享输入。fan-in 关闭时，成功分支输出 ID 为其任务 ID；开启时汇总输出 ID 为 `final`，原输入按 `$input` 作为整体插入。有汇总模型时，其失败不能以纯拼接结果冒充成功。

定时触发不与同一 Workflow 已排队或活动运行重叠，服务重启不补齐所有错过的时间点。全局运行、来源和分析并发分别受限，为 1 时确实串行。

### 恢复前置条件

| 待继续工作 | 必要材料与边界 |
| --- | --- |
| 失败分支重试 | 原快照、原共享输入、所有已成功分支正文；只执行未成功分支。 |
| 尚未发布的汇总 | 原快照、所需分支结果；引用 `$input` 时需要原共享输入。已成功汇总结果不得静默重跑。 |
| 冻结后补发 | 原快照、完整 final 和已持久化回执；跳过成功和不确定投递，只处理明确失败或尚未发送项。 |
| 输入或成功正文缺失 | 报告缺失范围并拒绝依赖该内容的续跑，不调用来源或模型“补成”原结果。 |

冻结后补发不要求 collection 和 analysis 仍然保存；原快照与 final 的完整性仍为必要条件。`recoverable=True` 只是材料提示，Workflow 还要确认确有可安全继续的操作。恢复不确定发送窗口仍可能存在重复风险，系统不承诺跨外部平台的恰好一次投递。

## 8. 交互与生命周期

外部 HTTP 是产品约定，框架选择不属于接口契约。错误响应为 `ErrorResponse`，各路由使用前缀 `/api`。

| 方法与路径 | 对外能力 | 成功结果 |
| --- | --- | --- |
| `GET /api/{kind}` | 列出五类资源之一。 | 200，资源列表。 |
| `POST /api/{kind}` | 校验后创建资源，重复 ID 冲突。 | 201，保存后的资源。 |
| `GET /api/{kind}/{id}` | 读取资源。 | 200，资源对象。 |
| `PUT /api/{kind}/{id}` | 完整替换已有资源；路径与正文 ID 一致。 | 200，保存后的资源。 |
| `DELETE /api/{kind}/{id}` | 删除未被引用的资源。 | 204，无正文。 |
| `GET /api/plugins` | 查询 Collector/Channel 能力与发现诊断。 | 200，DiscoveryReport 的语义形状。 |
| `POST /api/workflows/{id}/run` | 受理一次新运行。 | 202，SessionRecord。 |
| `GET /api/sessions` | 按 workflow_id 和有界正整数 limit 查询。 | 200，SessionRecord 列表。 |
| `GET /api/sessions/{id}` | 查询运行状态、投递和恢复信息。 | 200，SessionRecord。 |
| `GET /api/sessions/{id}/artifacts/{name}` | 查询四种固定阶段正文之一。 | 200，与 name 对应的 ArtifactContent。 |
| `POST /api/sessions/{id}/resume` | 使用原材料受理恢复。 | 202，SessionRecord。 |
| `POST /api/sessions/{id}/cancel` | 取消并等待状态写回。 | 200，SessionRecord。 |
| `GET /api/health` | 查询服务是否可用及组件诊断。 | 就绪或可降级服务为 200，必要能力不可用为 503；返回 HealthReport。 |

触发和恢复响应包含 `Location: /api/sessions/{id}`。HTTP 断开不自动取消已接受的任务；业务失败从 session 查询。固定路由不能被通用资源路由吞掉，阶段名称不能解释为任意文件路径。

| 错误类别 | HTTP 状态 |
| --- | --- |
| 无效字段、schema、Workflow 内部引用或配置关系 | 422。 |
| 直接定位的资源或 session 不存在 | 404。 |
| 重复 ID、引用/状态冲突、恢复材料不足、已知 session 正文不可用 | 409。 |
| 有界执行队列容量不足 | 429。 |
| 必要存档不可用、服务未就绪或正在关闭 | 503。 |
| 未预期内部错误 | 500，返回脱敏说明和可关联诊断，不返回任意堆栈。 |

CLI 的外部能力包括生成离线配置样例、启动服务、资源管理、触发、查询、恢复和取消。业务命令调用相同 API，不直接执行 Workflow 或访问存档私有结构；启动和样例初始化由本地装配能力完成。

```python
class ApplicationLifecycle:
    async def start(self, config: SystemConfig) -> None: ...
    async def health(self) -> HealthReport: ...
    async def stop(self) -> None: ...
```

生命周期入口在必要配置和存档可用、模块装配完成后才接受任务。关闭先停止新准入和调度，再处理活动运行，最后释放插件与模型资源。所有后台工作都有归属，启动失败也必须释放已取得资源。该入口负责协调，不持有第二套 Workflow 业务规则。
