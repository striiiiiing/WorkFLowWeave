# AxonHub 巡检与 Hermes GitHub 更新

两条工作流使用真实来源，没有内置测试数据集：

- **应用巡检**：远端 AxonHub 的请求 SQLite → Streamable HTTP MCP → 错误优先 / 近期统计后置 → `gpt-5.6-luna` 压缩 → `gpt-5.6-sol` 分析成功与失败 → 文件报告。
- **GitHub 更新**：`gh api` 读取最近 7 天的提交及发布 → `gpt-5.6-sol` 分析 → 文件报告。`fan_in=null`，不额外调用汇总模型。

GitHub 仓库暂按 `NousResearch/hermes-agent` 配置，若用户所说的 hermas 指另一项目，修改 `github-source.json` 的 `--repo` 参数。两个工作流默认手动触发；本次不启动定时模型费用。

## 所需资源

| 文件 | 作用 |
| --- | --- |
| `server.py` | 只读 MCP 工具：错误尝试、近期请求统计与样本 |
| `axonhub-inspection-mcp.service` | 当前 myserver 的用户级 systemd 部署配置 |
| `mcp-server.json` | Streamable HTTP 服务 `/mcp` |
| `errors-source.json` | 错误来源、字段白名单与 token 限额 |
| `activity-source.json` | 近期成功 / 失败 / 取消统计及样本 |
| `ai.json` | 两段巡检及 GitHub 分析模型；凭据使用环境变量引用 |
| `channel.json` | 将结果追加到 `data/reports/inspection.log` |
| `workflow.json` | 两段巡检流程 |
| `github_updates.py`、`github-source.json` | gh CLI 提交与发布采集 |
| `github-workflow.json` | 只分析更新的流程 |

所选模型来自本次现有 AxonHub 模型目录；名称不是通用服务商的保证。导入其他环境前修改 API 地址、模型名称及引用。`base_url` 在后端环境访问；`http://127.0.0.1:19026/v1` 指本次已配置的模型接入地址，不是 MCP 地址。

## 远端 MCP

`myserver` 的部署位置为 `~/opt/workflowweave-inspection-mcp/server.py`，unit 为 `~/.config/systemd/user/axonhub-inspection-mcp.service`；数据库为 `~/opt/axonhub/data/axonhub.db`。

unit 复用已有 `~/opt/workflowServer/.venv/bin/python`（已安装 `mcp==1.30.0`），不修改该环境。其他环境可独立运行：

```bash
uv run --script examples/workflows/axonhub-inspection/server.py \
  --database /实际路径/axonhub.db --port 19036
```

服务只绑定远端回环地址，通过 SSH 暴露给本地后端。先在独立终端保持以下连接：

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 127.0.0.1:19036:127.0.0.1:19036 myserver
```

远端状态与维护：

```bash
ssh myserver 'systemctl --user status axonhub-inspection-mcp.service --no-pager'
ssh myserver 'journalctl --user -u axonhub-inspection-mcp.service -n 30 --no-pager'
ssh myserver 'systemctl --user restart axonhub-inspection-mcp.service'
# 不再需要时停用新部署的 MCP
ssh myserver 'systemctl --user disable --now axonhub-inspection-mcp.service'
```

数据库以 `mode=ro` 与 `query_only` 读取；只提供固定查询，不接受任意 SQL。字段白名单排除请求/响应正文、headers、凭据、客户端 IP；错误摘要排除凭据与 URL，最长 1,200 字符。数据库或 Schema 不匹配会明确报错。

## 本地导入

先在**后端进程的环境**设置 `WORKFLOWWEAVE_INSPECTION_API_KEY`，不要把密钥写进 JSON 或 Git。`gh` 也必须在后端 PATH 中；使用后端相同用户登录 GitHub，或提供有权读取目标仓库的 `GH_TOKEN`：

```bash
gh auth login --hostname github.com
gh auth status
```

从仓库根目录启动后端，CLI 来源的相对脚本路径按后端工作目录解释。其他启动目录请把来源 `argv` 中的脚本路径改为绝对路径。按依赖顺序导入：

```bash
export WORKFLOWWEAVE_API_URL=http://127.0.0.1:4300
uv run workflowweave resource save mcp_servers examples/workflows/axonhub-inspection/mcp-server.json --create
uv run workflowweave resource save sources examples/workflows/axonhub-inspection/errors-source.json --create
uv run workflowweave resource save sources examples/workflows/axonhub-inspection/activity-source.json --create
uv run workflowweave resource save ai examples/workflows/axonhub-inspection/ai.json --create
uv run workflowweave resource save channels examples/workflows/axonhub-inspection/channel.json --create
uv run workflowweave resource save workflows examples/workflows/axonhub-inspection/workflow.json --create
uv run workflowweave resource save sources examples/workflows/axonhub-inspection/github-source.json --create
uv run workflowweave resource save workflows examples/workflows/axonhub-inspection/github-workflow.json --create
```

重复导入明确选择 `--replace`。文件渠道需要 `plugins/channel/file` 可用；资源导入不自动登录 GitHub或安装外部命令。

## 字段、顺序与预算

错误来源先于近期统计。两者先各自处理，再按 `workflow.sources` 顺序共享一个总输入预算，超长时后面的统计来源可能被截取或省略，前面的错误也受其单来源预算约束。

| 项目 | 配置 | 理由与边界 |
| --- | --- | --- |
| 时间窗口 | 24 小时 | 一次日常巡检；可调整 MCP 参数 `hours`（1–168） |
| 错误样本 | 最多 60 次失败尝试，最新在前 | 限制明细量；重试失败不等于请求最终失败 |
| 近期样本 | 最多 30 个请求，最新在前 | 状态总计独立覆盖整个窗口，样本不代表全量明细 |
| 错误字段 | 白名单 + 256 tokens / 标量 | 保留请求、通道、模型、时间、状态和简要错误 |
| 来源预算 | 错误 5,000 / 近期统计 3,500 tokens | 优先分配异常详情，再补近期情况 |
| 总输入预算 | 7,500 tokens | 限制压缩模型输入；来源包装和省略标识也计入 |
| 压缩输出预算 | 最多 2,500 tokens，提示词要求约 800 字 | 输出预算包含服务商的推理 token；字数是指令而非精确强制限制 |
| 强模型输入 | 仅 `compress` | `order=["compress"]`，不带 `$input`，关闭单任务优化 |
| 模型超时 / 重试 | 300 秒 / 0 | 给推理调用有限预算；演示不自动重试并重复计费 |
| GitHub | 最近 7 天、每端点一页 30 条 | 达到一页上限会标明覆盖限制，不声称完整历史 |

Workflow 按压缩模型 `gpt-5.6-luna` 的已知 `o200k_base` tokenizer 限制输入；这是当前路由名称对应的本地计量规则，服务商账单 token 仍以返回 usage 为准。GitHub 使用有已知 tokenizer 的 `gpt-5.6-sol`。改用未知 tokenizer 的模型并保留 token 限额，会明确返回 `tokenizer_unavailable`。

## 运行与预期输出

```bash
uv run workflowweave collect axonhub_errors
uv run workflowweave collect axonhub_activity
uv run workflowweave run axonhub_inspection
uv run workflowweave collect hermes_github_updates
uv run workflowweave run hermes_github_updates
uv run workflowweave sessions --limit 5
```

在 Web 的工作流和运行记录中检查本次运行，报告落在配置数据目录的 `reports/inspection.log`：

- 巡检先给出异常证据，再分析最终成功、最终失败、取消与失败尝试的区别，引用可见请求 ID，列出待核查项；它不会自动执行修复。
- GitHub 简报列出功能、修复及可能的兼容性变化，并引用 commit SHA / release URL；采集只取提交说明与发布说明，不表示审查了代码 diff。
- 采样、字段裁剪或来源省略会降低覆盖范围；报告需明确这一限制，不能凭不完整数据声称全量故障率或时间趋势。
- SSH / MCP / 模型 / gh 失败应出现在对应阶段。缺少 GitHub 登录会返回 CLI 错误，不生成成功简报。

本次实际运行证据、token 与成本见仓库的 [演示验证记录](../../../docs/production-demo.md)。测试数据集与质量对比、最低硬件要求仍待后续验证。
