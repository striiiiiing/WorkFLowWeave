# Manager 四层配置注入任务

状态：设计、实现、主代理审查及验证完成。本次设计变更新建任务，原模块 task.md 保留。

## 依据与决策

- 用户授权按新 manager design 更新设计、新建任务并实施。依据 [Manager](../../modules/manager%20design.md)、[Collection](../../modules/collection/design.md)、[Channel](../../modules/channel/design.md)、[Config](../../modules/config/design.md)，proposal.md 不修改。
- 根因是插件 defaults、实例和调用设置混用 options，Workflow 只有 ID 引用。按结构性修正，ResourceStore 统一展开，options_schema 仍是字段唯一来源，避免另建 invocation schema 漂移。
- x-logagent-workflow 布尔注解默认未标记，即实例字段，因为 host/key 应保存一次而非由 Workflow 改写。保留实例调用默认值；显式调用覆盖只接受声明字段。
- overrides 默认空对象表示无覆盖；Setter 空列表保留。Workflow 模板在实例默认值之后，符合四层优先级。不新增 timeout 默认值，沿用现有预算。
- 注册 API.config_path 提供插件私有 JSON 位置，插件自行读取；根配置只 enabled，旧 defaults 明确拒绝，不猜迁移。作者构造使用普通 Python 构造函数，不增加通用父类。
- Channel 按账户复用，send 显式传调用 options，避免收件人改变导致重建或污染实例。Mock path 仍是实例字段，email recipient 是调用字段。

## 清单

- [x] 同步 Manager、Collection、Channel、Config、Workflow、Email 设计及派生契约。
- [x] schema 注解、覆盖模型、资源候选校验与快照展开，保留缺失插件执行策略。
- [x] 插件私有配置入口、作者构造注入，移除框架 defaults 并更新相关示例及测试。
- [x] Channel 调用参数与账户级复用、内置邮件/Mock；内置 Collector 调用字段声明。
- [x] 多 Workflow 共享实例、覆盖权限、模板优先级、空列表、旧快照、插件错误、并发隔离回归。
- [x] 依次定向测试（每命令60秒）、lint、构建、真实烟测；审查 diff 并记录结果。


## 实现与审查记录

- WorkflowDefinition 增加 SourceOverride/ChannelOverride 映射；ResourceStore 在候选事务中检查引用、覆盖声明、模板归属、合并后的完整 schema/语义校验，再固定调用路径。快照展开使用同一入口，不在执行时读取当前模板或资源。
- options_schema 使用 x-logagent-workflow 顶层注解，未标字段保持实例属性；声明错误及调用层凭据明确拒绝。资源保存只延后必填调用字段，账户必填及条件凭据仍校验；完整调用语义校验在 Workflow 绑定时执行。
- 注册 API 提供只读绝对 config_path；插件自行读取、验证私有 JSON 并注入构造参数，异常撤销整个插件临时注册。移除 PluginSettings.defaults、注册视图 defaults 缓存及 expand_source.options_defaults；示例和测试同步迁移。
- ChannelManager 只按账户配置版本复用实例，工厂不接收 recipient，send 显式传调用选项；Email 每次取得收件人，账户中不保存调用选项。Mock path 保持实例配置。保留一次发送预算、回执、取消、关闭及卸载行为。
- 兼容边界：现有资源 options 可继续作为调用默认值；旧插件根 defaults 不再接受，旧渠道插件 send 必须增加 keyword-only options 参数。无静默兼容或默认收件人回退。README 已记录迁移。
- 原计划并行实现代理未返回结果，主代理接手完成并审查全部实现；设计审查代理另行请求为 GPT-5.5/high。未把未返回的审查算作完成证据。

## 验证

- 配置/渠道/Workflow 联合定向 157 passed；追加插件私有配置及真实 SMTP 收件人隔离后配置/邮件 81 passed。
- 新增真实 ResourceStore + CollectorManager + WorkflowService + SQLite 集成：共享实例的两套调用参数、旧 session 恢复、无重复通知；本地 SMTP 并发不同收件人仅一个账户实例及连接。
- 单次全套测试触及 60 秒硬超时（exit 124），未放宽时限；分组完整覆盖：配置/采集/AI/渠道等 437 passed（25.05 秒），Workflow/Session/Lifecycle/Interaction 170 passed（50.08 秒），均 exit 0。最后新增“直接 Email 调用不得回退到实例收件人”测试修正测试工厂缺少 port 后，Email 专项 30 passed（2.67 秒），当前共 608 项通过。
- Ruff 全目录检查、uv build、独立 examples/collect.py --collector mock 烟测通过；隔离临时插件目录的烟测返回 success/count=1；默认工作区 plugins 含同名 mock 声明，首次烟测明确报告既有注册冲突，内置采集仍成功，未修改该用户插件。修改范围 git diff --check 通过。第三方 LangGraph/Starlette 弃用警告保留，不属于本次配置变更。
- 主代理审查 schema 单一来源、候选事务原子性、调用层字段权限、缺失插件、账户实例身份与旧快照、明文与异常边界、测试真实性及兼容说明；既有无关 interaction/frontend/IDE 工作区变更不纳入本次提交。
