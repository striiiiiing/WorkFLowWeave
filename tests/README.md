# 测试导航

按**被测职责**选择位置：单一业务模块的测试放 `tests/<模块名>/`；共享契约和跨模块贯通测试留根目录。依赖其他模块不自动等于跨模块测试，例如 Lifecycle 的装配职责仍归 lifecycle。每个测试文件顶部说明覆盖逻辑、验证手段与依赖边界；新增用例时同步更新该说明。归属有疑问时先明确该文件验收的不变量由哪个模块负责，再决定位置；不要仅凭文件名前缀分类。

| 位置 | 职责与文件 |
| --- | --- |
| `ai/` | `test_service` 验证服务编排；`test_env` 验证环境配置解析；`test_channels`、`test_live` 验证 HTTP 渠道契约与真实调用。 |
| `channel/` | `test_channel_manager` 管理实例、并发与清理；`test_channel_mock` 验证文件投递；`test_email_channel` 使用回环 SMTP 验证协议和失败语义。 |
| `collection/` | `test_manager` 验证采集管理与隔离；`test_mock` 验证过滤/排序等离线采集；`test_logs` 验证有界日志读取；`test_history` 验证 session 历史读取。 |
| `config/` | `test_config` 验证插件发现与配置发布；`test_credentials` 验证凭据边界；`test_resource_store` 验证资源持久化、引用及原子快照。 |
| `interaction/` | `test_interaction` 验证 HTTP 参数、服务委派、状态码与错误脱敏。 |
| `lifecycle/` | `test_lifecycle` 验证装配、健康、reload 与关闭；`test_lifecycle_logging` 验证日志组件所有权、轮转与脱敏。 |
| `workflow/` | `test_session_store` 验证业务存档；`test_workflow_interval` 验证定时触发；`test_workflow_lifecycle` 验证准入/关闭竞争；`test_workflow_recovery` 与 `test_workflow_process_recovery` 验证协程中断及进程强退恢复。 |
| 根目录 | `test_contracts`、`test_schema_annotations`、`test_shared_session_models` 是共享契约；`test_starter_resources`、`test_workflow_integration`、`test_workflow_overrides` 验证跨模块调用链。 |
| [前端测试](../frontend/tests/) | 前端独立包沿用 `unit/`（API 客户端、JSON 字段、查询参数）和 `e2e/`（界面流程与真实模型验收），由 Vitest/Playwright 发现，不由 pytest 执行。 |

## 辅助模块

- `workflow_ai_helpers.py`：跨模块复用的 LangChain 模型传输替身，通过 `tests.workflow_ai_helpers` 显式导入。
- `workflow/helpers.py`：Workflow 恢复及生命周期测试共享的采集/AI/通知替身与快照构造器；不要从另一个 `test_*.py` 导入。
- `ai/conftest.py` 与 `ai/live_helpers.py`：HTTP 渠道夹具和环境配置工具，作用域限制在 AI 测试包。
- `frontend/tests/serve_backend.py`：Playwright 的临时后端启动器。

## 运行

以下命令从仓库根目录执行，先用 `uv sync` 安装 Python 开发依赖。后端每条命令使用 60 秒硬超时；完整套件应分组运行，避免进程恢复耗时挤占其他组预算。

```bash
rtk proxy timeout 60s uv run pytest tests --collect-only -q
rtk proxy timeout 60s uv run pytest tests/config tests/collection -q
rtk proxy timeout 60s uv run pytest tests/channel -q
rtk proxy timeout 60s uv run pytest tests/interaction tests/lifecycle -q
rtk proxy timeout 60s uv run pytest tests/workflow --ignore=tests/workflow/test_workflow_process_recovery.py -q
rtk proxy timeout 60s uv run pytest tests/workflow/test_workflow_process_recovery.py -q
rtk proxy timeout 60s uv run pytest tests/test_*.py -q
rtk proxy timeout 60s uv run pytest tests/ai/test_env.py -q
```

单独运行模块或文件时直接指定新路径，例如 `rtk proxy timeout 60s uv run pytest tests/collection/test_history.py -q`。根目录新增包标记是为了稳定导入，不添加 sys.path 修改或全局夹具。

`tests/ai/test_service.py`、`tests/ai/test_channels.py` 和 `tests/ai/test_live.py` 默认会向 `http://localhost:19026/v1` 发送真实 HTTP 请求，需要预先启动兼容服务；不是内存 MockTransport。`LOGAGENT_AI_LIVE=1` 会额外启用 Qwen 用例，环境文件由 `LOGAGENT_AI_ENV` 指定，默认 `.env`。端点不可用应表现为真实失败，不修改跳过规则掩盖环境问题。

网络验收分别执行，确保每条命令仍受 60 秒硬超时约束：

```bash
rtk proxy timeout 60s uv run pytest tests/ai/test_service.py -q
rtk proxy timeout 60s uv run pytest tests/ai/test_channels.py -q
rtk proxy timeout 60s uv run pytest tests/ai/test_live.py -q
```

前端在 `frontend/` 执行 `npm test`、`npm run typecheck`；普通浏览器测试先 `npm run build` 再 `npm run test:e2e`（需要 Playwright Chromium）。`npm run test:live` 操作现有前后端服务并创建/清理测试资源，连接要求见对应测试文件顶部与配置。保持测试名和断言语义稳定，目录整理不等于产品行为变更。
