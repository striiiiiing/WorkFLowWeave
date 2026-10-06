# Tasks

## 依据与范围

本任务基于用户本轮确认、`f175e03` Collector/Agent 基线和 `bf9fc1c` MCP SDK 基线。旧 `redesign-mcp-schema-first` 内容已删除，不作为设计依据。本变更只恢复 Agent MCP 工具和必要的 Workflow 调用/交接能力，不恢复整个 Collector 系统。

## 实施任务

- [ ] 1. 重写 MCP 服务模型，允许 Cursor `mcpServers` 原始键名作为 ID，并分离显示名称、凭据引用和 transport 配置。
- [ ] 2. 基于官方 MCP SDK 重构 runtime 目录探测：优先 `server/discover`，兼容回退 `tools/list`，保留目录缓存和工具 schema。
- [ ] 3. 保留并重构现有固定 `mcp` `ToolDeclaration`，明确 `list/search/describe/call` 的 schema-first 语义，复用 Agent 调度、事件和 ArtifactStore，移除 Collector 路由；不新增平行顶层工具；`call` 与 Bash 一样使用普通并发调度，不套用文件系统 `Read` 的 `exclusive` 限制。
- [ ] 4. 实现现有 `mcp` 代理 `call` action 的当前 schema 参数校验、原始结果保存、调用阶段和结果未知语义。
- [ ] 5. 实现 Cursor JSON 导入，覆盖 `command/args/env/url/headers`，敏感值进入凭据引用，不写入普通配置和 Agent 上下文。
- [ ] 6. 重写 Workflow MCP 调用描述，保存服务、工具和原始参数；删除对 Collector registry、Setter、模板和旧 count 成功判定的依赖。
- [ ] 7. 实现 `_meta.workflowweave_count` 的严格非负整数读取；缺失或非法统一记录 `count_unavailable`，零值进入空业务结果。
- [ ] 8. 将 MCP 请求错误映射到 `stop/notice/skip`；明确区分请求失败、空结果、计数不可用和结果未知。
- [ ] 9. 重写 Workflow 到 Agent 的交接，交接来源名称、MCP 服务名称、工具名称和参数作为声明式调用描述；CLI 交接来源名称和指令；由 Agent 自己调用；恢复和分支使用持久化描述。
- [ ] 10. 增加真实 stdio MCP、Cursor JSON、server/discover 回退、schema 校验、零计数、计数缺失、错误策略和未知结果测试。
- [ ] 11. 运行后端目标测试、类型/静态检查、前端构建和最小真实 MCP smoke test。
- [ ] 12. 执行 `openspec validate redesign-mcp-schema-first --strict --no-interactive`，复核相对链接、契约一致性和 diff。

## 决策依据与默认值

- MCP SDK、transport、目录缓存和原始执行事实：复用 `bf9fc1c` 已实现并验证的基础能力。
- Agent schema 插件和统一调度：复用 `f175e03` 的 `ToolDeclaration`、事件和执行框架；MCP 路由重新实现。
- 当前固定 `mcp` 代理已具备 list/search/describe/call 的 schema-first 外形：依据 subagent 对 `bf9fc1c` 的代码检查，不新增三个顶层工具，只补齐目录探测和交接语义。
- `_meta.workflowweave_count`：按用户要求增加专用前缀，避免通用 `count` 与其他元数据冲突。
- `count_unavailable`：按用户要求统一表示字段缺失或非法，不从正文推算。
- `server/discover` 优先、`tools/list` 回退：按用户要求兼容新版和旧版探测能力。
- Cursor 原始键名作为 ID：按用户要求保留用户配置中的服务身份，不再套用旧资源 ID 正则。
- MCP `call` 不采用 `exclusive`：按用户要求，多个 MCP 请求并发是正常场景，文件系统 `Read` 的互斥限制不适用于 MCP 或 Bash。
- 敏感值首次可由前端填写；提交后只通过受保护凭据引用复用，敏感值为空时默认要求选择复用凭据：按用户要求兼容首次配置和后续复用流程。
- MCP Workflow 来源请求错误统一服从用户可配置的 `on_error`；未配置时使用 `SourceConfig.on_error` 的默认值 `notice`，按 `stop`、`notice` 或 `skip` 处理；Agent 直接调用时将工具错误原样返回，不套用 Workflow 策略。
- 默认 lazy 探测、5 秒探测上限、单飞重连和未知调用不重放：依据用户提供的 pi-mcp-adapter 健康探测机制；实现前如需改变应新增设计决策。
