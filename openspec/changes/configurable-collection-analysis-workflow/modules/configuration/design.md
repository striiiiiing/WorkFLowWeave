# 配置与资源管理模块：设计

依据 [模块提案](./proposal.md) 与 [总体设计](../../design.md) §3.1–§3.2。
实现文件为 `logagent/models.py`、`logagent/config.py`，本模块不调用具体采集、模型或投递实现。

## 1. 系统架构

### 1.1 组件与依赖

| 组件 | 职责 | 调用方 |
| --- | --- | --- |
| 公共模型 | 配置结构、结果状态、错误及快照类型 | 全部模块 |
| 系统配置读取 | JSON 解析、结构校验、相对路径归一 | 服务启动入口 |
| 插件配置读取 | 单个可选 JSON 文件的读取与错误分类 | Collector / Channel 插件发现 |
| `ResourceStore` | 五类资源的原子存取和引用检查 | 业务服务、API |
| 快照装配 | 从一致资源视图生成独立配置副本 | Workflow |

结构校验与文件存取不依赖业务模块，避免 `config → workflow → config` 循环。
各业务服务先执行自己的语义校验，再调用 Store 保存；Workflow 负责整体验证。

### 1.2 配置与文件布局

系统配置是独立 JSON 文件，`SystemConfig` 字段以总体设计为准。
`data_dir`、`plugin_dir`、`log_file` 的相对路径都以系统配置文件目录为基准。
解析路径不触发插件加载、模型请求、邮件发送或 Workflow 运行。
`ResourceStore(root, *, base_dir=None)` 的根目录由启动入口传入，建议为 `data_dir/resources`。
服务装配时传入 `base_dir=config.base_dir`，使内置 file Channel 的 `options.path` 以系统配置文件目录为基准；独立使用 Store 时默认以 root 为基准。该字段在资源文件中保留用户填写的路径，快照才展开为绝对路径。未知插件 options 中的 `path`、`*_path` 可能是 JSONPath、远程路径或来源相对路径，必须原样保留，由所属业务模块按声明解释。
每个资源保存为 `<root>/<kind>/<id>.json`，`kind` 只允许五个固定种类。
系统配置错误应阻止半配置服务启动；单个插件配置错误由插件管理器隔离。
插件级同名 JSON 的读取归发现模块，配置内容经 `registry.plugin_config` 注入 `register(registry)`。
发现模块调用公共协程 `load_plugin_config(json_path) -> dict` 读取单个文件；文件不存在返回空对象，不创建文件。非对象、非法 JSON 或非有限数值返回 `PLUGIN_CONFIG_INVALID`，磁盘读取失败返回 `PLUGIN_CONFIG_UNAVAILABLE`，错误 details 只带文件名，不回显配置内容。发现、逐文件隔离与插件 schema 校验仍由插件管理器负责；此入口不修改系统配置。

### 1.3 校验分层

1. 公共模型检查类型、必填字段、枚举、数值范围和未知字段。
2. Store 检查资源种类、标识、引用存在性及模板所属 Collector。
3. Collector、AI、Channel 验证各自的声明、能力与专属参数。
4. Workflow 在保存与启动前组合上述检查，验证输入、分支、fan-in 和通知整体关系。

`options/setters/model_options` 是明确的扩展容器，容器内部规则由所属模块解释。
扩展容器不意味着顶层允许任意字段，也不意味着可绕过插件 schema。

## 2. 技术选型（ADR）

待后续讨论。

## 3. 接口契约

### 3.1 公共模型

所有公共输入模型采用严格结构，`extra="forbid"`，错误保留字段路径。
ID 为 1–80 位 ASCII 字母、数字、下划线或短横线；不接受路径分隔符。
超时与 `interval_seconds` 为正数；并发上限至少为 1；`retries` 为非负整数。
数值不接受字符串或布尔值转换；开关只接受 JSON 布尔值。
日期时间使用带时区的 UTC；不使用无时区字符串表达 session 或快照时间。

| 模型 | 本模块必须固定的约束 |
| --- | --- |
| `SystemConfig` | 总体设计中的服务与路径字段；合法端口与正数运行并发上限 |
| `SourceConfig` | Collector 标识、options、setters、可选 template；四种来源策略分别校验 |
| `SetterTemplate` | `id/collector/setters`，只能应用于同一 Collector |
| `AIConfig` | 环境变量凭据引用；拒绝顶层和 `model_options` 内的 `temperature/top_k` |
| `ChannelConfig` | 标识、options、timeout、retries、enabled；额外尝试次数不含首次调用 |
| `AnalysisTask` | 唯一 task ID、AI 资源 ID、prompt，首版不引入来源子集或 Agent 模式 |
| `FanInConfig` | order 仅引用本 Workflow 分支，`$input` 最多一次；空 order 使用声明顺序 |
| `BackupPolicy` | stages 仅为 `snapshot/collection/analysis/final`；保留天数有值时必须为正 |
| `WorkflowDefinition` | 来源与 Channel 引用为有序 ID 列表，分析为有序 `AnalysisTask` 列表 |

`collection_concurrency/analysis_concurrency` 独立配置，为 1 时约定串行执行。
`analysis_failure` 为 `stop/continue`，`on_all_empty` 为 `stop/skip`。
`on_all_empty=skip` 的含义是结束且不分析、不通知，不得改作“空输入照常执行”。
公共模型同时定义 `CollectionResult/AnalysisResult/Notification/DeliveryResult/SessionRecord`。
来源状态为 `success/empty/filtered_empty/missing/failed/timeout`。
分析状态为 `success/failed/timeout/cancelled`，投递状态为 `success/failed/timeout/skipped`。
session 状态沿用总体设计；`source_statuses/analysis_statuses` 是状态映射，`deliveries/errors/artifacts` 保存回执、错误和索引，`missing_artifacts` 是阶段到原因的映射。`output_frozen` 默认 false，是不受内容备份开关影响的管理字段。`LogAgentError(code, message, details)` 的内容可安全返回 API。
`delivery_uncertain` 是投递错误原因，不在这里发明另一种成功状态。

### 3.2 Store 协程入口

| 方法 | 返回 | 保证 |
| --- | --- | --- |
| `save(kind, model, *, mode="upsert")` | 保存后的模型副本 | `create/replace/upsert` 的存在性检查与写入共用锁，成功后才替换旧资源 |
| `get(kind, id)` | 对应模型副本 | 缺失、JSON 损坏和结构无效有不同错误原因 |
| `list(kind)` | 模型列表 | 按 ID 稳定排序，不返回临时文件或半解析对象 |
| `delete(kind, id)` | 无返回内容 | 先查反向引用，有引用则报冲突 |
| `snapshot(workflow_id)` | `WorkflowSnapshot` | 同一锁内解析完整引用，返回深拷贝 |
| `resolve(definition)` | `WorkflowSnapshot` | 对尚未保存的 Workflow 只读解析引用，供完整业务验证，不写资源 |

所有方法为 `async`；磁盘操作经工作线程执行，不直接阻塞事件循环。
同一服务只装配一个管理资源根目录的 Store，操作共享一把异步锁。
锁内内部读写使用不重复获取同一锁的辅助函数，避免嵌套 get/list 造成死锁。
列表发现损坏资源时报告资源 ID 与原因，不默默当作不存在。
损坏原因区分 `invalid_json`、`invalid_schema` 与 `id_mismatch`；结构校验错误保留字段路径，不回显输入值。
资源不存在映射为 404，引用冲突为 409，输入配置错误为 422。
内部磁盘不可用返回结构化服务错误；错误不带绝对秘密内容或任意堆栈。

### 3.3 引用与删除

反向引用包括 `workflow.sources → sources`、`source.template → setters`。
还包括 `analysis.ai/fan_in.ai → ai` 和 `workflow.channels → channels`。
删除检查与实际删除在同一锁内完成，错误 details 列出引用资源及字段路径。
保存不会擅自删除旧模板或其使用者；同 ID 保存表示显式更新该资源。
Workflow 的分支 ID、来源引用和 Channel 引用不得出现导致歧义的重复项。
fan-in order 的未知分支和重复 `$input` 必须在启动前拒绝。
动态 Collector/Channel 是否存在、工具与提供方是否可用，由对应业务验证器确认。

### 3.4 配置快照

统一类型为 `WorkflowSnapshot`，不能在不同模块间混用裸字典和模型对象。

| 字段 | 类型与含义 |
| --- | --- |
| `workflow` | `WorkflowDefinition`，本次完整 Workflow 定义 |
| `sources` | `dict[str, SourceConfig]`，按来源 ID 索引，Setter 已展开 |
| `ai` | `dict[str, AIConfig]`，覆盖全部分析及可选 fan-in 使用的 AI |
| `channels` | `dict[str, ChannelConfig]`，按目标实例 ID 索引 |
| `created_at` | UTC 带时区时间，表示生成快照的时刻 |

按 Workflow 的声明顺序收集引用；映射用于定位，执行顺序始终读取 Workflow 列表。
模板展开先复制模板 setters，再使用实例 setters 覆盖同名键，不修改模板资源。
展开后的 SourceConfig 不再需要读取模板才能执行；保留 template ID 仅用于来源追踪。
任何缺失资源或模板 Collector 不匹配都使整个快照失败，不返回半成品。
快照为独立深拷贝；原资源修改、返回对象修改与已有快照彼此隔离。
构造或反序列化快照时，资源映射必须恰好覆盖 Workflow 引用的资源，映射键必须与资源内的 ID 一致，缺失、额外或错配资源均被拒绝。
快照保留 `api_key_env` 等凭据引用，不保存环境变量解析结果。
Workflow 在触发时对快照完成业务语义验证，再交给 `ArchiveStore.create` 持久化。
恢复只使用存档中的此类型配置，不重新调用 `snapshot(workflow_id)` 获取最新版。

## 4. 非功能性约束与验证

写入流程为校验、加锁、序列化、同目录临时文件写入、flush/fsync、原子替换。
替换前异常保留旧文件，临时文件在 finally 中清理；没有旧文件时不得暴露新半文件。
工作线程写入完成或失败之前不提前释放操作锁；取消调用不允许后台写入越过后续写操作。
读取返回新模型，禁止用可变共享缓存绕过磁盘语义与锁。
当前只承诺单进程内一致性；不把 asyncio.Lock 描述为多个 uvicorn worker 的协调机制。
配置读取、列表和快照不得产生外部请求，也不把“校验资源”变成隐式执行。
测试覆盖严格字段、引用与删除、Setter 展开、快照隔离、并发一致性及原子写故障。
边界测试需验证模型保留不同错误/空状态，而非仅测试对象可以被构造。
测试仅使用临时目录及占位环境变量，不依赖宿主机秘密或真实外部服务。
模块测试完成后记录结果；后续具体业务接入时补充其语义校验集成测试。
