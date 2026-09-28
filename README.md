# LogAgent

Python 3.11+ 的异步采集与分析工作流，提供 FastAPI 服务、命令行客户端和 Vue 3 管理界面。当前采集来源为 MCP 服务工具或 CLI 命令；采集保留原始结果，Workflow 再生成供 AI 使用的输入视图。

```bash
uv sync --group dev
uv run logagent config-example --output config.json
uv run logagent start --config config.json
```

前端启动方式见 [前端说明](frontend/README.md)。本次契约和实现决策见 [MCP/CLI 变更](openspec/changes/collect-from-mcp-and-cli/tasks.md)。

## 资源与调用

资源文件使用 v4 格式，包含 `sources`、`mcp_servers`、`ai`、`channels` 和 `workflows`。旧 Collector/Setter 来源不会自动迁移；请先备份旧配置，再显式创建等价的 MCP 或 CLI 来源。

CLI 来源有两种执行方式：`argv` 分开指定可执行文件和参数，`shell` 指定完整命令；两种方式都可设置工作目录。MCP 来源引用服务 ID、原始工具名和 JSON 参数。MCP 服务可用 stdio、Streamable HTTP 或 SSE 连接；环境和 Header 中的凭据使用环境变量或加密凭据引用。

```json
{
  "id": "host_info",
  "call": { "kind": "cli", "mode": "argv", "executable": "uname", "argv": ["-a"], "cwd": null },
  "limits": { "item_tokens": null, "field_tokens": null }
}
```

保存资源可使用 `logagent resource save sources source.json --create`。单次采集使用 `logagent collect host_info`；MCP 来源可通过 `--arguments` 指向形如 `{"arguments":{"limit":10}}` 的 JSON 文件覆盖工具参数，CLI 不接受非空 MCP 参数覆盖。`logagent collect-schema SOURCE_ID` 返回公开调用参数 schema。

共享 MCP 目录 API 为 `/api/mcp/catalog/status`、`/api/mcp/catalog`、`POST /api/mcp/catalog/{server}/load?refresh=true` 和 `/api/mcp/catalog/{server}/tools/{tool}`。目录查询可按服务和关键词筛选，并使用 `cursor`、`page_size` 分页；目录未加载、加载失败和无工具是不同状态。

Workflow 的 `input_processing` 选择 `none`、`ison`、`toon`、`zon`、`md` 或 `csv`，以及总输入、单项、字段 token 限额。未设置限额表示不主动截取；来源只可覆盖单项和字段限额。JSON 内容按配置转换，普通文本保留原文表示。结果分别记录获取状态与输入视图状态，不自动统计业务条数。

## 运行与恢复

Workflow 使用 SQLite 保存运行状态和阶段历史。触发返回 session ID；显式取消使用 `workflow.cancel(session_id)`，恢复使用 `workflow.recover(session_id)`。已有执行意图但回执未知时不会自动重放外部调用。Agent 接续 Workflow 时继承该次运行的 MCP 服务范围，并通过固定 `mcp` 代理按需查询目录、描述工具和调用；CLI 来源不会扩展 Agent 的 MCP 范围。

独立 CLI 采集示例见 [examples/collect.py](examples/collect.py)。
