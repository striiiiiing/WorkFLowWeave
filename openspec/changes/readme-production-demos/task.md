# README 真实巡检与 GitHub 更新演示

## 依据与范围

- 用户 2026-10-06 授权通过 `ssh myserver` 部署 Streamable HTTP MCP，读取 AxonHub 近期错误；本地配置错误优先、近期统计在后的工作流，弱模型压缩后交强模型分析成功与失败。
- 用户同时要求以 `gh` CLI 采集 hermas 的 GitHub 更新，只分析、不调用模型汇总。仓库身份待用户确认。
- 用户最初安排测试数据集后补、最低硬件待租机测试；2026-10-06 追加由 AI 设计测试集，优先公开数据，以 GPT-6 Luna max 作 judge，对照格式优化 / token 过滤与弱模型摘要 → 强模型分析。先完成当前演示，再实施评测；最低硬件仍等待用户租机。
- 来源契约依据 [MCP/CLI 采集提案](../collect-from-mcp-and-cli/proposal.md)；输入按 `workflow.sources` 顺序裁剪的实现依据 `src/workflowweave/workflow/input_processing.py:process_input`。
- 两段模型调用依据 [提示词与汇总设计](../align-workflow-prompt-contract/design.md)：强模型 `order=["compress"]`，关闭单任务优化，不重新传入 `$input`；GitHub 工作流 `fan_in=null`。
- 不修改既有 proposal.md / design.md，不修改无关会话、重命名或 Agent 实施中的文件。

## 决策与默认值

- AxonHub 数据来自只读 SQLite 请求/执行记录；容器日志探针无返回，数据库可读取状态及错误字段。请求与执行次数分开，避免把重试成功当成最终失败。
- MCP 只监听远端 `127.0.0.1:19036`，本地经 SSH 转发访问 `/mcp`，复用 SSH 身份认证。服务只提供两个读取工具，不提供 SQL 或任意命令入口。
- 默认窗口 24 小时、最多 60 条错误尝试和 30 条近期请求，用于一次完整日常巡检；采样覆盖范围随输出明确记录。
- 字段白名单排除 request/response body、headers、凭据与客户端 IP；错误摘要先脱敏再限制 1,200 字符。Workflow 字段预算及来源/总预算另外按已知模型 tokenizer 执行。
- 默认手动触发，先验收实际输出；不在缺少频率约定时启动周期性模型费用。
- 先检查现有模型目录再选择压缩/分析模型；token 限额必须有当前 `AIService.input_counter` 支持的模型，未知 tokenizer 明确失败，不增加估算 fallback。

## 实施与验收

### 真实联调发现的 MCP 绑定缺失

首轮 `3526a6291cdd495cacfffb7d9b0a3499` 在 collect 阶段报 `mcp_out_of_scope`，同一来源单独调用 API 成功。快照正确保存了 MCP 配置，但 WorkflowRunner 创建 CollectionContext 时未传入，图节点继续使用空绑定。修复为 WorkflowContext 构造时从唯一的固定 snapshot 派生 collection.mcp_servers；首次运行、显式 context 与恢复统一经过此处，不增加 API 绕过或当前资源读取。依据 redesign-workflow/design.md 的固定快照/运行上下文边界，补真实 stdio MCP 首轮与 collect 重跑回归验证，并验证运行后变更资源不影响旧快照。

远端新依赖首次下载未完成，部署改为直接使用已有、已确认含 mcp 1.30.0 的 Python 3.14.4 解释器，不修改原应用环境。脚本仍保留 PEP 723 依赖声明供独立安装；服务 unit 中解释器路径是部署前置条件。

### 当前版本截图的前端前置修复

Playwright 真实导航 `/workflows` 遇到 Vite 500 overlay：Agent 的 events/transcript/sessionProjection 已移入 `model/runtime`，消费者仍引用旧路径；相关类型应从现有 `model/public` 导出。只改这些陈旧 import 和对应测试，不新增兼容 re-export，也不重复实现 Agent 行为。旧 Workflow defaults 的 cronPresets 路径也按当前 `model/create` 调整。原 node_modules 未安装锁文件声明的 `@langchain/core` / `@langchain/vue`，按 README 执行 npm ci；验收目标是当前页面实际加载和截图，未授权重写前端行为。

对应测试还引用旧 runs/model/report，按现有 workflows/model/history/report 修正。定向前端测试累计 26 passed；Node 24.15.0 下类型检查与生产构建通过。README 的 Node 要求按锁定依赖 abbrev 5.0.0 / nopt 10.0.1 的 engines 更新为 22.22.2+（22.x）或 24.15.0+（24.x），不把原本会出现 EBADENGINE 的 24.14.0 声称为完整验收环境。开发依赖预构建曾发生 504 / 文件读取 cannot allocate memory；当前开发页已能实际加载，最终演示采用生产预览验证，避免多个开发进程竞争同一预构建缓存。

- [x] 实现并测试只读 MCP 工具：错误详情、近期成功/失败/取消统计。
- [x] 部署远端常驻服务并通过真实 MCP SDK 调用验证；probe 返回 `healthy`，工具数为 2。
- [x] 本地导入巡检 MCP、来源、模型、文件渠道、工作流并完成真实运行；成功 session 为 `83c74cef296e4352b3a76989b01441c2`。
- [x] 配置 gh 更新采集及仅分析工作流；因未登录，真实采集按预期返回 CLI 非零错误并停止。
- [x] 使用项目现有 Playwright / Chromium 对真实生产预览验收巡检配置、成功报告与 GitHub 配置；保存当前版本截图及检查证据，README 已替换旧图。三页无 pageerror / console error / HTTP ≥400；GitHub 页面配置通过不代表其来源已成功运行。
- [x] 记录本次调用、token、AxonHub账面成本与实际运行环境；新增公开数据和6条件成本对照见 [LLM评测任务](tasks/2026-10-06-llm-evaluation/task.md)。judge因上游额度/限流尚未评分，最低硬件仍待用户租机。
