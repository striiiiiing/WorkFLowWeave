## MODIFIED Requirements

### Requirement: MCP 服务配置支持 Cursor 包络

系统 SHALL 在保留现有单条 `MCPServerConfig` 资源接口的同时，接受 Cursor 风格的对象配置。配置根 SHALL 为 `servers`，并可接受等价的 `mcpServers` 根键；每个服务名称键 SHALL 直接作为该服务的稳定身份，允许 `-` 等现有 ID 合法字符。服务值的 `type` SHALL 映射到现有 MCP transport，`stdio` 至少支持 `command`、`args` 和可选 `cwd`。

#### Scenario: 添加带连字符名称的 stdio 服务

- **WHEN** 用户在 JSON 模式提交

  ```json
  {
    "servers": {
      "qqmusic-mcp": {
        "type": "stdio",
        "command": "qqmusic-mcp",
        "args": ["stdio"]
      }
    }
  }
  ```

- **THEN** 系统保存一个身份为 `qqmusic-mcp` 的 MCP 服务，transport 为 `stdio`，command 和 args 与输入一致，并可在 MCP 列表中查到

#### Scenario: 一次导入多个服务

- **WHEN** JSON 包络包含多个服务名称键且所有值均有效
- **THEN** 系统一次性保存全部服务；任一服务校验失败时不保存其中任何服务

#### Scenario: 未显式切换 JSON

- **WHEN** 用户打开新建 MCP 服务编辑器但没有点击“编辑 JSON”
- **THEN** 页面仍显示字段表单，保存行为和现有单条 MCP 资源接口保持不变
