# Design

## 1. 边界与复用

这是结构性重设计，不在旧 Collector 上增加一层 MCP 适配。保留 `bf9fc1c` 的 MCP SDK connector、stdio/SSE/Streamable HTTP transport、配置版本目录缓存、分页目录刷新、JSON Schema 参数校验、原始 MCP 返回和 `phase/result_known` 执行事实。

保留 `f175e03` 的 `ToolDeclaration`、Agent 统一排程、调用事件和 ArtifactStore 展示机制。旧 `PluginGateway` 的 `sources:id`、Collector options/setters 和 CollectorManager 不复用；MCP 由新的服务身份、工具名和 schema 路由。

## 2. Schema-first Agent 接口

Agent 继续注册一个固定的 `mcp` 代理工具，复用现有 `ToolDeclaration` 和统一调度框架。代理的 `action` 使用以下操作：

- `list`：返回服务状态、工具原名、截断描述和分页信息，不返回完整参数 schema。
- `search`：按名称或描述搜索目录，返回命中工具的紧凑结果和后续查询线索。
- `describe`：按服务和工具返回完整 `inputSchema`；schema 不截断，过大的 schema 使用 ArtifactStore 引用。
- `call`：按服务身份和原始工具名定位工具，刷新或读取目录，按当前 schema 校验参数，然后调用 MCP。

MCP 代理（包括 `call`）不使用文件系统工具的 `read` 或 `exclusive` 调度类别。MCP 调用可以并发发送多个请求，这是正常的使用方式；同一轮可以调用同一服务或不同服务的多个工具。它与 Bash 一样不受只针对文件系统 `Read` 等工具的互斥限制。MCP 运行时负责连接、transport 和服务级别的并发约束，不能把文件系统工具的调度限制扩展到 MCP。代理 schema 是稳定的，不枚举服务和工具目录。无需增加 `mcp_list`、`mcp_search`、`mcp_call` 三个平行 Agent 工具。

## 3. 服务身份与 Cursor 导入

MCP 服务模型拆分 `id` 与 `display_name`。Cursor JSON 的 `mcpServers` 键名原样作为服务 `id`，同时作为默认显示名称；不得套用旧资源 ID 的字符集限制，但必须拒绝空字符串和重复键。内部引用使用长度受限的编码或数据库键，不能改变用户可见的原始 ID。

Cursor 的 `command`、`args`、`url`、`headers`、`env` 按 transport 归一化。敏感值允许在前端首次配置时直接填写；提交后写入现有受保护存储或 credential 引用，不写入 Agent 提示、普通事件和目录缓存。已有服务再次编辑时不回显明文；敏感值为空表示默认复用已有凭据，由前端显示复用选择器。新建服务且没有可复用凭据时，仍允许直接填写并创建凭据；用户也可显式切换到首次填写或替换模式。导入错误必须明确返回，不用空服务替代。

## 4. 目录探测与健康检查

连接、显式刷新、调用前校验和 keep-alive 探测均优先尝试 `server/discover`；服务未声明或返回不支持时回退到 `tools/list`。`tools/list` 仍是旧版兼容和目录刷新手段。目录缓存只保存工具元数据，不保存凭据和调用结果。

默认生命周期为 lazy：首次列表、搜索或调用才连接。keep-alive 服务器可按配置周期探测，单次探测超时 5 秒，同一服务单飞重连并使用有界退避。连接在请求发出前失效时最多重连并重试一次；调用已发出且结果未知时不得自动重放。

## 5. 计数与请求状态

MCP 结果中的专用业务计数字段为 `_meta.logagent_count`，值必须是非负整数。字段缺失、类型错误或路径不符合约定时，调用仍可成功，但计数状态为 `count_unavailable`；系统不从正文推断计数。

请求状态和业务计数分离：

- `isError=true`、超时、传输错误、协议错误、服务/工具不在绑定范围：请求错误。
- 正常返回且 `_meta.logagent_count = 0`：空业务结果，不是请求错误。
- 正常返回但计数缺失或非法：请求成功，计数状态 `count_unavailable`。
- 已发送但结果未知：保留执行阶段和未知事实，按请求错误策略处理，不自动重放。

## 6. stop / notice / skip

Workflow 来源配置中的 `on_error` 是用户选项，取值为 `stop`、`notice` 或 `skip`，并统一处理该来源的各种 MCP 请求错误。参数校验失败、服务或工具不存在、服务越界、连接/transport 错误、协议错误、工具返回 `isError`、超时以及结果未知都进入该选项：`stop` 阻止后续 Workflow 阶段；`notice` 记录错误并继续；`skip` 跳过当前来源并继续。未配置时使用现有 `SourceConfig.on_error` 的默认值 `notice`，不把错误静默转成成功。Agent 直接通过 `mcp` 代理调用时没有 Workflow 来源策略，错误作为 Agent 工具错误返回，由当前对话决定后续动作。零计数和 `count_unavailable` 不触发 `on_error`，而进入各自的空结果或计数不可用处理。

服务停用、越界、工具不存在、schema 校验失败属于调用未成功建立或派发的 MCP 请求错误，按 `on_error` 处理；不再建立 Collector 时代的 `missing` 成功分支。

## 7. Workflow 与 Agent 交接

MCP 来源保存来源名称、Cursor 配置中的原始 MCP 服务名称、工具名称、原始 `arguments`、执行结果和计数状态。继续对话时只交接一个声明式调用描述，不交接已连接的 MCP 对象、完整服务配置或全量 schema，也不自动重放原调用。Agent 收到这些名称和参数后，自行通过现有 `mcp` 代理执行 `list/search/describe/call`，并可根据当前对话修改参数后再次调用。服务凭据仍由运行时绑定解析，不进入提示文本。

CLI 来源交接来源名称和原始 command/args 或 shell 描述，由 Agent 自行决定是否继续执行；不授予 MCP 能力。恢复和分支使用已持久化的调用描述，不从当前全局资源重新推导名称或参数。
