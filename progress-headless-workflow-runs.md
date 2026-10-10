# 无头 Workflow Runs QA 进度

## 范围与安全边界

- 对照 `openspec/changes/redesign-workflow/proposal.md`、`design.md` 与 `tasks/2026-09-28-frontend-live-workflow/task.md`；本轮只验证现有行为，不修改 OpenSpec 设计文档。
- 只使用无头 Chromium/Playwright，目标端口为前端 `13000`、后端 `14300`；所有 shell 命令经 `rtk` 执行。
- 原仓库 `data/` 约 7.1 MB，已复制到 `/tmp/logagent-headless-qa-data`，服务的 `data_dir` 指向副本，原数据库不由本轮测试写入。
- 触发用例限定为无数据源、`on_all_empty=stop`、无通知渠道的工作流；预期在 collect 后结束。不会提交恢复/重跑请求，不调用模型，也不发外部通知。

## 环境就绪

| 检查项 | 状态 | 证据 |
| --- | --- | --- |
| 前端 `127.0.0.1:13000` | 已启动 | `GET /` → HTTP 200 |
| 后端 `127.0.0.1:14300` | 已启动 | `GET /api/health` → HTTP 200，`status=ready`、`accepting_runs=true` |
| QA 数据副本 | 已就绪 | 由仓库 `data/` 复制；API 当前返回 0 条历史运行 |
| Playwright | 已就绪 | 本地版本 1.63.0，测试将使用无头 Chromium |

## 场景进度

| 场景 | 状态 | 说明 |
| --- | --- | --- |
| 运行列表按字段筛选 | 待测 | 正向筛选临时运行，并检查请求参数与结果行 |
| 第一页空数据 | 待测 | 使用不存在的 workflow ID，检查空态、页码与下一页禁用 |
| history/运行详情 | 待测 | 由真实触发生成仅含 collect 事实的历史记录 |
| retry/阶段重跑 | 待测 | 仅验证入口、阶段可用性和再次发送说明；不确认执行 |
| recovery | 待测 | 检查恢复可用性 API/UI；不提交 POST |
| 手动触发非模型边界 | 待测 | 空来源策略停止；检查终态和阶段集合不含 analyze/aggregate/notify |
| SSE | 待测 | 检查真实 EventSource HTTP 状态、响应类型和终态快照 |
| 报告 | 待测 | 检查 aggregate 报告正文可用性及页面空报告状态 |
| 真实模型运行依赖说明 | 待测 | 记录为何不触发模型以及运行真实分析所需配置，不实际调用模型 |

截图目录：`docs/qa-headless-workflow-runs/`。逐项 HTTP、console、pageerror、截图及结论将在最终报告和本进度表中补齐。
