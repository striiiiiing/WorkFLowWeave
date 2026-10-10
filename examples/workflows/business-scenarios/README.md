# 三个业务工作流示例

这三个例子都由 WorkFlowWeave 的 MCP、LangChain/LangGraph 工作流和流式运行器执行，结果发送到已经配置的 QQ 渠道。它们是可替换的业务模板：新闻源可以换成日志、审计记录或其他信息源；股票标的和 GitHub 仓库也可在来源 JSON 中替换。示例不包含密钥、QQ 密码或私有地址。

## 1. LLMs as a lossy compressor：新闻源（可替换为日志等信息）

`news-lossy-compression.json` 先用 Fetch MCP 读取 BBC World RSS 的多条带摘要、时间和链接的新闻，再由 `gpt-6-luna` 按业务目标压缩，最后由 `gpt-6.1-sol` 只读压缩卡片完成研判。`fan_in.order` 只有 `compress`，关闭单任务优化且不带原文 `$input`，因此可以观察有损交接边界。实际使用时应替换为企业允许访问的新闻或日志 MCP，并检查正文覆盖。

## 2. 股票分析 fan-out / fan-in

`stock-fanout-fanin.json` 针对 NVDA 建立三个固定方向的 Luna Agent：经营财务、估值行情、风险事件。每个 Agent 启用 `mcp` 和 `read`，必须实际调用已绑定的 yfinance MCP 搜索，再按职责读取财务、行情或事件证据；Sol 汇总三个独立结果。fan-out 表示职责拆分，`analysis_concurrency=1` 使三个分支串行执行。搜索可能含其他股票的报道，须核对相关性；限流、数据延迟或 NO_DATA 不能视为成功证据。

## 3. GitHub issue 任务分工（无 fan-in）

`github-issue-task-split.json` 从 `pallets/flask` 的开放 issue 搜索最新一条，同时读取该仓库 README。第一项是较强的 Sol LLM，依据 README 的业务承诺判断严重度和修理必要性；第二项是较弱的 Luna Agent，通过 GitHub 官方 MCP 读取评论和实际涉及文件，有关联 PR 时才继续读取 PR。`fan_in` 为 `null`，两份输出保持独立，避免把业务优先级误当作技术根因。

## 准备 MCP

```bash
# Fetch MCP（固定版本）
uvx mcp-server-fetch==2026.8.18
# yfinance MCP（固定版本，需要 Python 3.12）
uvx --python 3.12 yfmcp==0.14.0
# GitHub 官方 MCP v2.0.0：从 release 下载 github-mcp-server，放入 PATH
export GITHUB_PERSONAL_ACCESS_TOKEN='只在当前 shell 设置，不写进 JSON'
```

先确认 `github-mcp-server --version`，再通过项目的 MCP 工具列表检查工具名和参数。若账户不能访问 GitHub，请先设置最小权限的只读 token。新闻和 yfinance 不需要额外 API key，但外部网络失败必须在运行记录中保留。

## 导入和运行

启动项目后端（`WORKFLOWWEAVE_API_URL` 指向实际服务）。将 `ai.json` 中的示例地址换成部署环境的 AxonHub 地址，密钥在后端环境通过 `WORKFLOWWEAVE_INSPECTION_API_KEY` 提供。实际路由使用 inspection_ai，工作流资源名称为 business_examples_ai。Sol medium、Luna xhigh，全部 streaming=true、retries=0。个人配置不能写进本目录。

先准备已有 QQ 通知渠道，将工作流的 `channels` 替换为其资源 ID，或在私人资源库把已有渠道复制为 `business_qq`。本次实测用服务器已有的 `qwenpaw_notify` 插件 `qqsend` 能力，由 QQ 机器人持有默认收件人；这是部署环境的插件，不是仓库内置 SDK QQ 的免配置承诺。新服务器须安装该插件和 qqsend，或配置项目内置 QQ 渠道。个人收件人和密码只留在渠道。

本次 Agent 设置 `preview_tokens=16000`、`output_tokens=16384`、`read_concurrency=1`。前者容纳搜索结果中的超长 JSON 字符串行，避免默认 2000-token 预览令 read 无法前进；第二项包含 Luna xhigh 的思考输出；最后一项串行执行工具。它们是实例设置，可在 Agent 设置页调整。API 方式须先 GET `/api/agents/config`，将返回的 `config` 与 `agent-runtime.json` 合并后 PUT `/api/agents/config`；该接口替换完整配置，直接提交三个字段会将其余设置恢复默认。这影响该实例全部 Agent，先保留原设置。

输入限额用实际下载的 tiktoken `o200k_base` 文件计算，`tiktoken_model_name=gpt-4o` 是此编码的本地映射，不发给上游，也不代表已证明路由模型的真实 tokenizer。服务商 usage 单独保存。

以下命令在仓库根目录执行；重复导入将 `--create` 改为 `--replace`。先把修改后的资源放到私人配置目录，并用下面的 EXAMPLES 指向它。

```bash
export WORKFLOWWEAVE_API_URL=http://127.0.0.1:4300
EXAMPLES=examples/workflows/business-scenarios
uv run workflowweave resource save mcp_servers "$EXAMPLES/news-mcp-server.json" --create
uv run workflowweave resource save mcp_servers "$EXAMPLES/yfinance-mcp-server.json" --create
uv run workflowweave resource save mcp_servers "$EXAMPLES/github-mcp-server.json" --create
uv run workflowweave resource save ai "$EXAMPLES/ai.json" --create
uv run workflowweave resource save sources "$EXAMPLES/news-source.json" --create
uv run workflowweave resource save sources "$EXAMPLES/stock-financials-source.json" --create
uv run workflowweave resource save sources "$EXAMPLES/stock-valuation-source.json" --create
uv run workflowweave resource save sources "$EXAMPLES/stock-risk-source.json" --create
uv run workflowweave resource save sources "$EXAMPLES/github-issue-source.json" --create
uv run workflowweave resource save sources "$EXAMPLES/github-readme-source.json" --create
uv run workflowweave resource save workflows "$EXAMPLES/news-lossy-compression.json" --create
uv run workflowweave resource save workflows "$EXAMPLES/stock-fanout-fanin.json" --create
uv run workflowweave resource save workflows "$EXAMPLES/github-issue-task-split.json" --create
uv run workflowweave run news_lossy_compression
```

CLI run 返回 session ID，不等待执行完成。用 `uv run workflowweave session SESSION_ID` 检查状态，新闻结束后再运行 `stock_fanout_fanin`，股票结束后再运行 `github_issue_task_split`。从项目阶段历史及 Agent 历史检查来源、工具调用、流式状态、usage、QQ 回执和输出；外部错误不能记作通过。三个工作流均为手动触发、无 schedule，模型无重试。

新闻 prompt 在 Codex 交接摘要基础上加入跨境数字订阅业务目标、信息保留优先级及省略范围。实际输出可能沿用“下一步”结构，而非严格的事实卡样式；本例验证业务筛选和交接，没有通用 prompt 对照。RSS 是标题及摘要，不是全文。

三个例子已在隔离实例通过真实模型调用和 QQ 通知；成功与失败轮的 session、费用、输出限制及备份说明见 [实测记录](../../../docs/business-scenarios-validation-20261007.md)。GitHub MCP 返回的嵌入文本资源必须进入共享输入，不能只看到下载状态就认定 README 已提供。

## 版本与限制

Fetch `mcp-server-fetch==2026.8.18`、yfinance `yfmcp==0.14.0`、GitHub 官方 MCP release `v2.0.0`。GitHub 示例使用动态“最新开放 issue”，所以每次运行的 issue 编号应写入 session 记录；它不是固定数据集。股票数据来自 Yahoo Finance 的非官方接口，新闻 RSS 的正文深度由源站决定。模型响应、费用和通知失败都以项目实际记录为准。
