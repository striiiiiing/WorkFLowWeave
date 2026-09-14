元信息
- 关联规范：[总设计](../../design.md)、[配置模块设计](./design.md)、[数据模型 §1–3、§6](../../contracts/data-models.md)、[模块接口 §2、§9](../../contracts/module-interfaces.md)。
- 任务总数：8。
- 预计执行时间：约 10 小时人工开发时间；单任务 60–90 分钟，独立任务可并行。

执行范围：Task 1–3 是本轮 collection 所需的配置前置能力，现已完成；Task 4 在接入需要凭据的 Collector 时执行，离线内置来源只依赖凭据接口。Task 4–8 尚未执行完毕，留待配置模块完整实现。

执行记录（2026-09-13）：
- Task 1 已完成：发布只读 Collector/Channel 注册视图，隔离 schema、字段、描述和 defaults 副本；捕获稳定 collect/create 及可选同步 validate 实现。
- Task 2 已完成：提供 `expand_source(source, *, collector, template=None, options_defaults=None)`，独立执行 schema 默认值、插件默认值、实例覆盖和 Setter 展开；成功后清除模板引用，语义校验收到独立参数副本。
- Task 3 已完成：实现异步 ConfigurationReader 和 PluginRegistry，支持包内相对导入、一个插件多能力、禁用、入口约束、原子回滚、稳定顺序和脱敏发现诊断。共享基础代码同时支持 Channel 声明注册，未实现网关或插件生命周期重载。
- 验证：`rtk proxy uv run pytest -q tests/test_config.py` 通过 48 项；`rtk proxy uv run ruff check src/logagent/config tests/test_config.py` 通过。真实 `MockCollector` 经注册、来源展开和执行，返回 success、count=1。
- 后续边界：未实现 ResourceStore、主密钥/凭据落盘、`reload_plugins` 与 owner 生命周期清理，不能据此将 Task 4–8 标记完成。

依赖执行：公共契约完成后开始 Task 1；Task 2 和 Task 3 可在 Task 1 后并行；Task 4 与注册工作独立。Task 5 → Task 6 → Task 7 按顺序执行，Task 8 在 Task 3 后独立推进。业务语义校验通过注入接口连接，避免 ResourceStore 与业务服务互相提交形成环依赖。

# Task 1: 建立只读注册视图与声明事务

描述：本轮 collection 前置，预计 60 分钟。定义配置模块持有的能力注册容器及只读视图，先使采集管理器能够按名称取得声明和实现；Collector 与 Channel 的查询边界共用注册基础设施。

输入：contracts.ID、contracts.CapabilityDescription、contracts.DiscoveryReport、contracts.ErrorInfo，以及 Collector/Channel 声明协议。

输出：config.CollectorRegister、config.ChannelRegister 的 get/describe 能力；插件级临时注册集合、owner 索引及声明校验入口。

依赖：公共契约模型与声明协议；不依赖 collection.CollectorManager 或 channel.ChannelManager 的实现。

验收标准：
- get 返回正确能力或 None；describe 返回独立描述对象，修改返回内容不能修改注册表或其他调用者的 schema。
- 校验 JSON Schema 2020-12 对象声明、能力名、必需实现/异步工厂及 Collector 异步 collect；未知或不合法声明给出可关联的错误。
- 同 kind 重名、覆盖内置名称或跨 kind 注册均被拒绝；某插件一项声明失败时，其本轮所有能力都不对外可见。
- 一个插件能够一次提交多个同类能力，全部有效时整体发布；业务模块无法通过只读视图新增或删除声明。

# Task 2: 实现 options 默认值与 Setter 展开

描述：本轮 collection 前置，预计 60 分钟。提供保存/导入时使用的纯配置规范化函数，固定默认值和 Setter 模板解释规则；本任务不实现资源持久化。

输入：contracts.SourceConfig、contracts.SetterTemplate、能力 options_schema/setters_schema、插件 defaults 及实例显式参数。

输出：config.expand_source(source, *, collector, template=None, options_defaults=None) 等纯规范化能力，返回独立且可校验的有效来源配置；该能力不依赖完整 ResourceStore。

依赖：Task 1；公共来源和 Setter 契约，以及 schema.validate_instance/schema_defaults。

验收标准：
- options 按 schema 默认值、插件 defaults、实例显式键的顺序覆盖；同名复杂值整体替换，不隐式深度合并。
- defaults 只能引用所属插件注册的能力及 schema 允许的字段；可只提供部分必填字段，最终实例必须满足完整 schema。
- Setter 先复制模板再覆盖实例显式键；显式空列表有效，其他模板键保留，输入模板及实例不被修改。
- 模板不存在、collector 归属不符或出现未声明 Setter 时返回可定位的校验错误；options 与 setters 不相互混入。
- 成功展开后 template=None，表示执行时无需回查模板；对已展开配置再次规范化不会重新读取模板或改变固化值。

# Task 3: 实现配置读取和 Collector 插件发现

描述：本轮 collection 前置，预计 90 分钟。由配置模块读取系统/插件设置、发现外部 Collector 并发布注册结果，让 collection 只消费注入的能力；Channel 扩展和完整重载归 Task 8。

输入：contracts.SystemConfig、PluginManifest、PluginConfiguration、插件目录及注入的内置 Collector 声明。

输出：config.ConfigurationReader、config.PluginRegistry.discover_plugins 的 Collector 路径、只读 collectorRegister 和可关联的 DiscoveryReport。

依赖：Task 1；插件 defaults 的部分字段校验约定与 Task 2 对齐，但发现过程不依赖 ResourceStore。

验收标准：
- 显式系统文件缺失或损坏报错；系统相对路径以配置文件目录解析；缺失插件配置视为空覆盖，不可读或非法 JSON 不按空配置继续。
- 先注册内置能力，再稳定排序扫描直接子目录；校验 manifest 必填字段、api_version 和入口为目录内相对 .py 路径。
- 禁用插件不导入入口；有效入口导出 plugin 并通过 register(api) 注册能力，入口调用不执行 shell 字符串。
- 无效 manifest、导入失败、同 kind 插件 ID 冲突、能力冲突或非法 defaults 只隔离相关插件并记录原因，其余有效 Collector 可调用。
- 针对一个插件多 Collector、失败无残留及缺失能力的集成用例，采集管理器无需自行扫描目录或导入入口即可取得结果和发现诊断。

# Task 4: 实现凭据保护与按需解析

描述：涉及受保护凭据的 Collector 时执行，预计 90 分钟；纯离线 collection 验收只需 contracts 中的注入协议。实现环境变量引用、认证加密封套和主密钥初始化。

输入：contracts.Credential、contracts.SystemConfig、环境变量、主密钥文件及已有密文存在性检查结果。

输出：config.CredentialManager.initialize/protect/resolve；可供 collection、ai、channel 注入的运行时解析能力。

依赖：公共凭据和系统配置契约；不依赖 collection、ai 或 channel 的业务执行实现。

验收标准：
- 优先使用配置指定的主密钥环境变量，再读取密钥文件；已提供密钥格式错误或文件不可读时明确失败，不生成替代密钥。
- 仅首次初始化、两处均无密钥且确认无既有密文时生成并安全写入；存在密文或无法确认时拒绝自动替换原密钥。
- protect/resolve 可往返还原；缺失环境变量、错误密钥、损坏密文或认证失败产生可识别错误且不覆盖原密文。
- 资源返回值、快照、日志和异常诊断不出现解析后的秘密；仅实际调用模块得到运行时明文。

# Task 5: 实现资源仓库与原子 CRUD

描述：后续配置模块任务，预计 90 分钟。建立五类资源的版本化 JSON 存储和单进程串行提交入口，业务校验器由调用方注入。

输入：全部资源契约、已确定 data_dir、注入的语义校验函数及候选资源。

输出：config.ResourceStore.save/get/list/delete、有效内存视图及 resources.json 原子持久化。

依赖：Task 1、Task 2；contracts.SourceConfig、SetterTemplate、AIConfig、ChannelConfig、WorkflowDefinition。

验收标准：
- 首次空目录可建立五个空集合；已存在但损坏或版本不支持的资源文件明确失败。
- create 拒绝已有 ID，replace 拒绝缺失 ID，upsert 支持两者；kind 与类型不符和未知顶层字段被拒绝。
- 保存先校验候选，再写同目录临时文件并原子替换，最后发布内存视图；注入文件写入失败后旧内容仍可读取。
- get/list 返回独立对象，列表按 ID 稳定排序；并发提交串行化，不丢失其他已提交资源。

# Task 6: 补齐引用校验与资源 reload

描述：后续配置模块任务，预计 90 分钟。在受控提交中校验直接及受影响引用，并复用该流程进行资源热更新。

输入：完整资源候选视图、当前有效视图、collection/ai/channel/workflow 注入的语义校验函数。

输出：受引用保护的 save/delete、config.ResourceStore.reload_resources 及结构化校验错误。

依赖：Task 5；collection.CollectorManager.validate、ai.AIService.validate、channel.ChannelManager.validate、workflow 定义语义校验能力。

验收标准：
- 来源和模板按 Collector 声明校验；模板 collector 不符、Workflow 引用缺失或资源更新破坏已有引用均拒绝整次提交。
- 删除被引用资源返回冲突，不级联删除 Workflow 或其他引用方。
- reload_resources 完整校验五类资源后一次发布；任何校验或读取失败均保留旧有效视图。
- 校验不执行采集、模型调用或通知，不反向调用 save 形成重入提交；错误能定位资源及字段。

# Task 7: 实现一致快照与来源路径固定

描述：后续配置模块任务，预计 60 分钟。从同一已发布资源视图装配 WorkflowSnapshot，固定 Setter、资源及能力声明要求解析的路径。

输入：已保存 Workflow ID 或未保存 WorkflowDefinition、完整有效资源视图及路径语义声明。

输出：config.ResourceStore.resolve/snapshot，包含独立来源、AI 和 Channel 资源副本的 contracts.WorkflowSnapshot。

依赖：Task 6；contracts.WorkflowSnapshot。

验收标准：
- resolve 不写资源，snapshot 只接受已保存定义；映射恰好覆盖引用且键与资源 ID 一致，执行顺序仍由定义列表决定。
- Setter 已展开，来源/渠道声明需要固定的相对路径成为稳定有效位置；不把所有名为 path 的扩展字段统一重写。
- 并发资源更新时一份快照只来自一版完整视图；后续更新资源或修改返回对象不会改变既有快照。
- 已保存来源的 Collector 暂时缺失不阻止生成快照；资源记录缺失或错配仍明确报错。
- 快照仅保留 Credential 引用或密文，不调用 resolve 把秘密写入快照。

# Task 8: 补齐 Channel 插件与 owner 重载

描述：后续配置模块任务，预计 60 分钟。在共享注册基础设施中接入 Channel 类型，并完成无活动运行前提下的 owner 清理、重新发现和视图发布。

输入：Task 3 的插件加载流程、ChannelType 声明、插件设置、装配模块保证的无活动 Workflow 条件。

输出：完整 config.PluginRegistry.channelRegister、reload_plugins 和 Collector/Channel 统一 DiscoveryReport。

依赖：Task 3；channel.ChannelType 声明协议；lifecycle 的准入关闭与无活动运行调用前置约定，可用测试替身验证，不等待完整生命周期实现。

验收标准：
- Channel 插件只能使用 register_channel，Collector 插件只能使用 register_collector；一个插件多同类能力原子发布。
- reload 按 owner 清理该插件的类型、schema 和工厂，重复执行不遗留旧声明或重复能力。
- 重载失败插件不进入新注册结果，其他有效能力仍可用；保存的来源和渠道资源不会被重载删除。
- 重载入口不自行取消当前调用；已发布旧视图的读取不因新视图发布被原地修改。
