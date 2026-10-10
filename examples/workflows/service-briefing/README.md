# 服务巡检简报示例

该目录提供一套可导入的最小 Workflow 资源。`source.json` 使用 `printf` 生成确定性的 JSON，因此不需要外部监控系统；接入真实环境时，把它替换成后端可执行的 CLI 或 MCP 来源。模型配置默认指向本机 Ollama 的 OpenAI 兼容端点，不包含任何凭据。

## 导入

先启动后端，并确保 `plugins/channel/file` 可用。然后在仓库根目录执行：

```bash
export WORKFLOWWEAVE_API_URL=http://127.0.0.1:4300
export WORKFLOWWEAVE_API_KEY=local-development-key
uv run logagent resource save sources examples/workflows/service-briefing/source.json --create
uv run logagent resource save ai examples/workflows/service-briefing/ai.json --create
uv run logagent resource save channels examples/workflows/service-briefing/channel.json --create
uv run logagent resource save workflows examples/workflows/service-briefing/workflow.json --create
```

`ai.json` 的 `base_url` 和模型名需要与实际 OpenAI 兼容服务一致；如果使用云服务，请改为服务商地址，并通过环境变量提供密钥。重复导入时将 `--create` 改为 `--replace`。

## 运行与预期输出

```bash
uv run logagent run service_briefing
uv run logagent sessions --workflow-id service_briefing --limit 1
```

在后端 `data/briefing.log` 中应看到包含 `service=api`、`status=ok`、`latency_ms=120` 和 `errors=0` 的巡检简报。模型输出可能因模型和提示词而异，但应包含状态、延迟、错误数和异常跟进结论。该示例默认手动运行；要每天 09:00 运行，可在 Web 工作流编辑器中设置 Cron。

## 所需资源

| 资源 | 文件 | 作用 |
| --- | --- | --- |
| CLI 来源 | `source.json` | 生成确定性巡检 JSON；真实部署可替换为 CLI/MCP 调用 |
| OpenAI 兼容模型 | `ai.json` | 分析巡检数据；需要可访问的 `base_url` 和模型 |
| 文件通知渠道 | `channel.json` | 将最终简报追加到 `data/briefing.log` |
| Workflow | `workflow.json` | 采集 → Markdown 输入 → 一项分析 → 文件通知 |
