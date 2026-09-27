# Manager 配置注入设计

Collection 与 Channel 共用四层配置边界。

| 层级 | 所有者与注入方式 | 生命周期 |
| --- | --- | --- |
| 作者构造 | 作者通过 Python 构造函数注入 SDK、客户端工厂、内部策略；Manager 接收已注册实现。 | 注册时构造，不序列化运行时依赖。 |
| 插件私有配置 | 注册 API 提供 config_path（插件目录内 config.json），插件自行读取 JSON、解释与验证并构造能力。根目录 config.json 只控制 enabled。 | 发现/reload 时读取；错误撤销本轮注册。 |
| 用户实例 | SourceConfig/ChannelConfig 的 id、options 保存可复用账户、host/key，也可保存调用选项默认值。 | 保存后固定，多个 Workflow 引用同一 ID。 |
| Workflow 调用 | source_overrides[id] 配置 options、setters、可选 template；channel_overrides[id] 配置 options。 | 保存时校验，快照展开并固定，每次调用显式传入。 |

## 声明与合并

唯一 options_schema 描述有效 options。顶层属性标注 x-logagent-workflow=true 表示可由 Workflow 设置的调用选项；未标注属性是实例配置，Workflow 不可覆盖。标注必须为布尔值，凭据不可标注为调用选项。能力描述直接暴露此 schema，框架不根据字段名猜测层级。Setter 属于调用设置。

合并顺序为 schema 默认值 → 实例显式 options → Workflow 显式调用 options；同名键整体覆盖，不深度合并，空列表仍是覆盖。插件私有 JSON 不被框架解释为 options defaults；旧根配置 defaults 明确拒绝，须迁移到插件私有文件或资源 options。

资源可暂缺必填调用选项（例如 recipient），但必填实例字段必须完整。保存 Workflow 时必须得到满足完整 schema 的有效配置。覆盖键必须属于已引用资源，options 只能填写标注字段；无效候选不得发布。

Setter 顺序为实例模板 → 实例显式键 → Workflow 模板 → Workflow 显式键；模板 collector 必须匹配。配置模块是唯一展开入口，Manager 只使用有效快照。资源/模板变更重新校验受影响 Workflow，删除其引用模板返回冲突。已保存配置的缺失插件仍在执行阶段报告，快照不要求插件在线。

## 调用与实例身份

Collector 保持 collect(options, setters, context)，收到合并后的有效值；作者构造依赖不放入 options。

ChannelManager.send(config, notification) 接收快照有效配置，按 schema 分离实例与调用 options。常驻实例按 channel_id、类型及实例 options 版本复用；create 只接收实例配置，send(notification, *, options) 显式接收本次调用选项。不同收件人复用同一账户连接，不把调用选项写回实例；账户变化创建新版本。enabled/timeout 不参与实例身份。

正文/metadata 不能覆盖配置；超时、取消、单次投递、恢复规则沿用所属模块设计。Mock path 是实例属性，email recipient 是调用属性；内置 Collector 的样例/查询范围 options 均为调用属性。

## 验证

验证作者构造和插件私有读取、禁用插件不读取、配置错误无残留；共享账户的多 Workflow 查询/Setter/收件人隔离、禁止覆盖实例字段、空列表与模板顺序、完整 schema 校验、旧快照稳定、渠道复用与并发调用隔离。
