## ADDED Requirements

### Requirement: Workflow 向 Agent 交接 MCP 使用范围

系统 SHALL 在继续对话时，将 Workflow 结果、原运行身份及其快照绑定的 MCP 服务引用交给 Agent 运行时。MCP 范围 SHALL 从该次运行启用的采集项中提取并按服务去重，包含采集失败或超时的服务，不随当前全局来源配置重新推导。交接 SHALL 保留来源项与服务、工具的关联供追溯，但不把采集项参数变成 Agent 后续调用的强制参数。CLI SHALL 不进入 MCP 范围。服务连接配置、凭据和全部工具 schema SHALL 不作为交接提示文本整体注入模型。

#### Scenario: 同一服务用于多个采集项

- **WHEN** Workflow 用同一服务的多个工具采集，且其中一个调用失败
- **THEN** Agent 继承一份该服务引用和相应来源关联，可按对话需要发现该服务的可用工具并重新指定参数，不被限制为原先成功的采集项

#### Scenario: 本次只有 CLI 来源

- **WHEN** Workflow 仅使用 CLI 采集项并继续对话
- **THEN** Agent 收到 Workflow 结果，本次继承的 MCP 范围为空，不因此取得全局 MCP 服务或自动将 CLI 包装成 MCP

### Requirement: Agent 通过固定代理入口按需发现 MCP 工具

Agent SHALL 采用 pi-mcp-adapter 的代理模式，通过单个模型可见的 `mcp` 工具提供服务状态、工具列表或搜索、指定工具描述和工具调用能力。其注册 schema SHALL 描述这些固定操作和通用参数，不枚举所有服务、工具名及各自参数 schema。Agent SHALL 能按服务筛选并分页发现工具，再按需取得选中工具的完整 schema。目录摘要 SHALL 提供可调用的明确身份、描述及加载状态；查询单个 schema SHALL 不触发业务工具调用。已知工具身份和参数时 SHALL 允许直接调用，不强制每次重复搜索。

#### Scenario: MCP 工具数量增加

- **WHEN** 本次范围内的服务从几十个工具增加至数百个工具
- **THEN** 模型常驻的 MCP 工具定义仍是固定代理 schema，额外工具定义仅在相应目录或描述结果中按需出现

#### Scenario: 发现后查看参数并调用

- **WHEN** Agent 需要某项能力但不知道具体参数
- **THEN** Agent 可搜索或列出相关工具、取得选中工具完整 schema，再携带服务身份、原始工具名和参数调用；其余工具 schema 不随之暴露

#### Scenario: 已知工具直接调用

- **WHEN** Agent 已从上下文获知工具身份和合法参数
- **THEN** Agent 可直接通过代理调用，由共享 MCP 层完成范围、可用性与参数校验

### Requirement: 模型可见 schema 与运行时目录分离

完整目录 SHALL 保存在运行时，模型默认只看到代理定义和如何使用它的说明。搜索结果 SHALL 返回有边界的摘要及后续分页或加载线索，不自动把命中工具注册为模型原生工具。完整 schema 超出 Agent 单次展示预算时 SHALL 提供可读取的完整内容引用并标识本次未完整展示；不能将被截断的 JSON schema 当作完整定义。模型可见的工具历史仍属于会话上下文，系统 SHALL 不声称按需返回的 schema 或工具结果没有 token 成本。

#### Scenario: 工具 schema 很大

- **WHEN** 单个工具的完整 schema 无法内联进入 Agent 单次输出预算
- **THEN** Agent 得到未完整展示的说明和可读取完整定义的引用；若完整读取能力不可用，则明确报错，不展示残缺 schema 冒充完整定义

#### Scenario: 搜索多个工具

- **WHEN** 一次搜索命中多个工具
- **THEN** 返回摘要与分页信息，下一轮注册工具集合仍保持代理模式，不因搜索而持续累积原生工具 schema

### Requirement: Agent 与 Workflow 共用原始 MCP 调用能力

Agent 的发现、描述与调用 SHALL 使用 [共享 MCP 能力](../mcp-runtime/spec.md)，并对本次继承范围采用一致的服务身份与可用性规则。Agent SHALL 直接调用 MCP，不能经由旧 Collector 或 Workflow 的输入处理入口。调用参数与结果 SHALL 不受 Workflow 的字段限额、单项限额、总输入限额或格式选择影响。工具关闭、调用调度、取消、事件记录及错误传播 SHALL 适用于代理分派的实际工具，不能因为外层工具统一叫 `mcp` 就把所有调用视为只读或绕过既有执行约束。

#### Scenario: 继续对话后再次调用 MCP

- **WHEN** Workflow 将某次 MCP JSON 结果截取并转为 CSV，而 Agent 在继续对话时调用同一 MCP
- **THEN** Agent 使用自己提交的参数并获得此次新调用的原始结果，不复用 Workflow 的 CSV 或限额视图，也不隐式合并采集项参数

#### Scenario: 代理分派可追溯

- **WHEN** Agent 通过代理调用某个 MCP 工具
- **THEN** 调用事件包含实际服务、工具、结果状态和调用关联；既有执行约束按实际调用生效，失败不被代理包装成成功

### Requirement: 原始结果与 Agent 展示预算分离

Agent SHALL 保留 MCP 原始结果的内容块、结构化数据和错误语义。适配模型消息或附件时 SHALL 保持内容语义，不应用 Workflow 转换。Agent 自身已有的上下文和工具输出预算 SHALL 独立生效；内联展示被截取时 SHALL 明示并提供可读取的完整结果引用，无法提供时明确报告限制，不能声称已获得完整原始结果。模型不支持的内容类型 SHALL 提供可用附件或明确的不支持状态，不静默丢弃。

#### Scenario: 原始结果超过 Agent 展示预算

- **WHEN** MCP 返回内容超过 Agent 自身单次工具输出预算
- **THEN** Agent 得到有标识的预览和可读取的完整结果引用；其预算取自 Agent，不取自 Workflow 格式或 token 限额

### Requirement: MCP 交接绑定随会话恢复与分支保留

系统 SHALL 将本次交接的 MCP 服务绑定作为 Agent 会话状态持久化，并在恢复与分支中保留。恢复 SHALL 使用原绑定及共享层的可用性检查，不重新继承当前全局服务目录；工具元数据可刷新，但不能因此扩大服务范围。原绑定无法恢复 SHALL 明确报告，不阻止读取已有 Workflow 分析结果。

#### Scenario: 创建会话后全局新增服务

- **WHEN** Workflow 接续 Agent 已创建，随后全局新增 MCP 服务，之后该 Agent 恢复或创建分支
- **THEN** 原会话及分支仍保留原 MCP 服务范围，不自动获得新服务
