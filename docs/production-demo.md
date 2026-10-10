# 生产演示验证记录

验证日期：2026-10-06（Asia/Shanghai）。这份记录只描述本次实际运行，不代表完整质量基准、长期稳定性或最低硬件验收。

## 产品演示

以下截图来自 2026-10-06 当前版本的真实配置与成功运行，不使用旧版本截图或模拟报告：

- [完整巡检配置：来源顺序、字段限额、两段模型与文件通知](../artifacts/production-inspection-config.png)
- [压缩模型与总输入预算](../artifacts/production-inspection-models.png)
- [巡检报告预览](../artifacts/production-inspection-result.png) / [完整报告](../artifacts/production-inspection-result-full.png)
- [GitHub 更新配置：只分析、不调用汇总模型](../artifacts/production-github-config.png)

真实浏览器检查覆盖上述两条工作流配置和巡检报告，页面错误、console error 与 HTTP ≥400 均为零。可复现脚本与证据为 [production-demo-browser.mjs](../artifacts/production-demo-browser.mjs) 和 [检查结果](../artifacts/production-demo-browser-results.json)。Tabbit 实例无法创建页面，因此此次使用项目已有的 Playwright / Chromium 对真实后端及生产预览页面验证；没有 mock 接口。当前本机预览为 `http://127.0.0.1:3010`，只在本次服务持续运行时可用。

本次运行报告为 `data/reports/inspection.log`，当前真实运行记录：

| 场景 | session | 状态 | 结果 |
| --- | --- | --- | --- |
| AxonHub 巡检（首次尝试，强模型上游 EOF） | `6b8eb17c1863412096e890a0aeab09fc` | failed at aggregate | 压缩已成功；强模型返回 502/EOF，系统保留失败证据 |
| AxonHub 巡检（重试） | `83c74cef296e4352b3a76989b01441c2` | completed | 采集 → 压缩 → 强模型分析 → 文件通知 |

第二次报告包含 24 小时窗口、错误采样限制、最终状态统计、重试后恢复与持续失败区分、请求 ID 证据和下一步检查建议；报告明确没有执行修复。

## 实例工作流

可导入目录：[examples/workflows/axonhub-inspection](../examples/workflows/axonhub-inspection/README.md)。

AxonHub 工作流使用 `myserver` 上的只读 SQLite，经 Streamable HTTP MCP 暴露两个固定工具。错误来源放在 `workflow.sources` 第一位，近期状态统计第二位；输入处理有来源级字段 / item 限额和总 token 限额，保证超长时后置统计先被裁剪。第一段使用 `gpt-5.6-luna` 压缩事实，第二段使用 `gpt-5.6-sol` 分析压缩结果，`fan_in.order=["compress"]` 且不带原始 `$input`；文件渠道保存最终报告。

GitHub 工作流使用 `gh api` 获取最近 7 天的提交和发布，每个端点最多 30 条，只含一个分析任务，不额外调用汇总模型。配置暂按 `NousResearch/hermes-agent`。本次 `gh auth status` 已通过，真实采集成功并取得 30 条提交、0 条 release；随后分析阶段因后端进程未获得模型凭据而返回 `credential_missing`，因此没有伪造成功简报，也没有进入汇总阶段。

## 成本与效果

本次 AxonHub 真实运行的 AI 阶段如下。费用来自 AxonHub `usage_logs.total_cost`，不是本地估算；输入包含 prompt cache，计费以服务端记录为准。强分析配置名 `gpt-5.6-sol` 在 AxonHub usage 中记录为实际上游 `gpt-6.1-sol`，因此成本表同时保留两者。

| 阶段 | 配置模型 | AxonHub 实际上游模型 | prompt tokens | completion tokens | total tokens | 账单费用 | 质量观察 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 压缩 | `gpt-5.6-luna` | `gpt-5.6-luna` | 11,128 | 728 | 11,856 | `$0.00121208`（request `201733`） | 输出事实简报，保留错误优先、窗口、采样限制与重试口径 |
| 强分析 | `gpt-5.6-sol` | `gpt-6.1-sol` | 854 | 3,257 | 4,111 | `$0.034278`（request `201775`） | 输出约 5,061 字符报告，区分最终失败、取消、重试恢复和待验证原因 |

运行频率为手动一次；本次巡检只调用 2 个 Workflow AI 阶段，每个阶段 1 次成功请求。首次强模型请求失败并产生一次失败调用，第二次运行成功；费用表只列成功运行的两阶段，失败调用的账单需按 AxonHub 同时段 request 记录另行归档。

历史 BGL 对照材料仍保留在 [旧评测记录](cost-quality-evaluation-20261006.md) 中，但不代表当前实验。当前成本与效果矩阵改用 Kaggle Synthetic Security Logs V1，比较 JSON/ZON/ISON 与是否弱摘要；输入全量进入 task 上下文，弱模型为 GPT-6 Luna、强模型为 GPT-6.1 Sol，judge 为 GPT-6 Luna max。首轮业务和 judge 存在上游 403/500 失败，不能据此宣称更便宜或更准确；逐条请求、实际 usage 和缺失账单见 `evals/results/20261006-kaggle-matrix/`。

## 已验证环境

| 环境 | 实测版本与结果 |
| --- | --- |
| 本地开发机 | Ubuntu 24.04.4 LTS / WSL2，Python 3.12.3（系统）、项目 `.venv` Python 3.11.15，Node.js 24.15.0，npm 11.19.1，uv 0.11.2；后端 `/api/health=200 ready`，生产页面真实浏览器检查通过 |
| `myserver` | Linux 6.8.0-111-generic，Python 3.14.4（WorkflowServer venv），Docker AxonHub `looplj/axonhub:v1.0.0-beta10`，远端 MCP systemd 服务 active；真实 MCP probe `healthy`，2 个工具 |
| 验证命令 | 巡检示例与 MCP Workflow 回归合计 15 passed；阶段重跑与巡检测试 12 passed；评测/输入裁剪回归37 passed；Ruff、离线 `uv build` passed；前端定向测试累计26 passed，typecheck、build与生产页面烟测通过 |
| 当前硬件 | 本地 WSL 可见 12 CPU、7.8 GiB RAM；这是测试机观测值，不是最低要求 |

最低 CPU / 内存尚未验证，等待租用测试机后补充。模型调用需要可访问的 OpenAI 兼容 API；GitHub 工作流另需后端 PATH 中的 `gh` 和有效登录凭据。

## 已知限制

- AxonHub MCP 错误明细是有限窗口、有限样本，字段和来源总预算会截断后置统计；报告会携带覆盖说明。
- AxonHub 路由可能把 Workflow 配置模型名映射为不同的实际上游模型名，成本记录使用服务端 usage 的实际值。
- GitHub 真实来源已完成登录后的真实采集验证（30 条提交、0 条 release）；分析阶段仍需后端进程注入有效模型凭据后重跑，当前失败记录为 `credential_missing`。
- 最低硬件、LLM judge 质量评分与长期运行频率尚未完成；已有同任务的格式/摘要路线成本对照，尚不足以证明效果优势。Luna max 的独立调用已验证可用，待渠道恢复后只需重跑 judge。
