# 支持 Cursor 风格的 MCP 配置导入

## Why

当前 MCP 服务编辑器只接受 LogAgent 内部的单条资源格式，并要求用户填写本地服务 ID。Cursor 风格配置以 `servers` 对象的键名作为 MCP 服务名称，连接字段使用 `type`；用户无法直接粘贴这类配置，名称中包含连字符时也没有从配置键建立服务身份的入口。

## What Changes

- MCP 服务编辑器继续默认使用字段表单，用户显式点击“编辑 JSON”后才进入 Cursor JSON 编辑模式。
- 前后端接受以 `servers` 为根、以服务名称为键的 Cursor 配置；每个键名直接成为保存后的 MCP 服务身份，保留连字符，不生成替代的本地服务 ID。
- JSON 导入支持一次导入多个服务，并以原子方式保存；已有字段表单和单条资源 API 保持兼容。
- 示例中的 `type: "stdio"`、`command` 和 `args` 能被转换为现有 MCP 运行时配置，导入后可在资源列表和来源选择器中使用。

不在本次范围内：改变 MCP 调用、目录缓存、凭据解析或已有单条资源的持久化结构；Cursor JSON 中的明文凭据不绕过现有凭据边界。

## Capabilities

- `mcp-runtime`: 增加 Cursor 配置的边界解析和服务名称映射，不改变运行时调用协议。
- `frontend`: MCP 服务编辑器提供显式 JSON 模式，并保留默认字段模式。
