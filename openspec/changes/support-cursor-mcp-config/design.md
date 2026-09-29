# 实现设计

## 外部格式与身份

后端新增独立的 Cursor 配置输入模型，根对象读取 `servers`，并兼容同语义的 `mcpServers` 别名；每个键名用现有 `ID` 约束校验，因此 `qqmusic-mcp` 这类连字符名称原样保留。值对象的 `type` 映射到现有 `transport`，省略 `type` 时按 Cursor 的 stdio 约定处理。解析结果转换为现有 `MCPServerConfig(id=<server-name>, ...)`，所以来源调用、快照和目录缓存仍只有一个服务身份来源。

Cursor 配置导入通过独立的 `POST /api/mcp_servers/import` 接口提交，后端先完整解析和校验全部服务，再调用资源仓库的批量发布接口，保证部分无效时不落盘。导入接口按“新增”语义拒绝已存在的名称；字段表单继续使用现有单条 create/replace API。现有 `env`/`headers` 仍必须符合凭据引用模型，不把 Cursor JSON 中的明文值静默写入资源。

## 前端交互

`MCPServerEditor` 以 `form` 为初始模式，新增一个显式的 `编辑 JSON`/`填写参数` 切换。JSON 模式编辑完整 Cursor 包络；新建时保存调用导入接口，字段模式和既有编辑资源仍走单条资源接口。切换回字段模式前必须成功解析为单一服务，多个服务 JSON 只允许作为新建批量导入提交。列表和来源选择器显示导入键名，但不再要求用户为 JSON 导入填写随机本地 ID。

## 验证

- 后端模型测试覆盖示例、连字符名称、`mcpServers` 别名、无效根/transport 和重复导入原子性。
- 前端单元测试覆盖默认字段模式、显式 JSON 切换、示例提交载荷和 JSON 语法错误。
- 运行后端定向 pytest（60 秒硬超时）、前端定向 Vitest、typecheck、Ruff 与生产构建；最后进行一次真实 HTTP MCP 资源添加烟测。
