# 待完成任务

已有 MCP/CLI 执行、目录缓存和调用校验基础；保留未核销的 schema-first 要求。Cursor 导入的原子校验与 JSON 模式任务合并到本入口，身份规则以本变更最新设计为准。

依据：[提案](proposal.md)、[设计](design.md)。

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
- [ ] 13. 核销 Cursor 包络、字段/JSON 模式切换、重复名称和无效批次不落盘的接口/UI 验收。
- [ ] 14. 统一 MCP JSON 新建、编辑与切换表单的转换契约，覆盖 enabled 字符串、非法 timeout/cwd、未知字段和 servers/mcpServers 根别名冲突。此项来自用户指定暂缓的 F2，本次整理不实施该修复。
