# 测试导航

按**被测职责**选择位置：单一业务模块的测试放 `tests/<模块名>/`；共享契约和跨模块贯通测试留根目录。依赖其他模块不自动等于跨模块测试，例如 Lifecycle 的装配职责仍归 lifecycle。每个测试文件顶部说明覆盖逻辑、验证手段与依赖边界；新增用例时同步更新该说明。归属有疑问时先明确该文件验收的不变量由哪个模块负责，再决定位置；不要仅凭文件名前缀分类。

| 位置 | 职责与文件 |
| --- | --- |
| `ai/` | `test_service` 验证服务编排；`test_env` 验证环境配置解析；`test_channels`、`test_live` 验证 HTTP 渠道契约与真实调用。 |
| `channel/` | `test_channel_manager` 管理实例、并发与清理；`test_file_channel` 验证文件日志投递；`test_email_channel` 使用回环 SMTP 验证协议和失败语义；`test_notification_plugin_adapters` 验证 QQ/Telegram SDK 适配；`test_agent_channels` 验证双向测试插件的 Agent 流程。 |
| `collection/` | `test_manager` 验证来源调用管理与隔离；采集器实现由插件提供，不在核心测试导航中维护内置采集器专属用例。 |
| `config/` | `test_config` 验证插件发现与配置发布；`test_credentials` 验证凭据边界；`test_resource_store` 验证资源持久化、引用及原子快照。 |
| `interaction/` | `test_interaction` 验证 HTTP 参数、服务委派、状态码与错误脱敏。 |
| `lifecycle/` | `test_lifecycle` 验证装配、健康、reload 与关闭；`test_lifecycle_logging` 验证日志组件所有权、轮转与脱敏。 |
| `workflow/` | `test_session_store` 验证业务存档；`test_workflow_interval` 验证定时触发；`test_workflow_lifecycle` 验证准入/关闭竞争；`test_workflow_recovery` 与 `test_workflow_process_recovery` 验证协程中断及进程强退恢复。 |
| 根目录 | `test_contracts`、`test_schema_annotations`、`test_shared_session_models` 是共享契约；`test_starter_resources`、`test_workflow_integration`、`test_workflow_overrides` 验证跨模块调用链。 |
| [前端测试](../frontend/tests) | 前端独立包沿用 `unit/`（API 客户端、JSON 字段、查询参数）和 `e2e/`（界面流程与真实模型验收），由 Vitest/Playwright 发现，不由 pytest 执行。 |

## 辅助模块

- `workflow_ai_helpers.py`：跨模块复用的 LangChain 模型传输替身，通过 `tests.workflow_ai_helpers` 显式导入。
- `fixtures/`：只供测试使用的 Collector、双向 Channel 和可安装插件包；不要将测试替身注册为产品默认能力。
- `workflow/helpers.py`：Workflow 恢复及生命周期测试共享的采集/AI/通知替身与快照构造器；不要从另一个 `test_*.py` 导入。
- `ai/conftest.py` 与 `ai/live_helpers.py`：HTTP 渠道夹具和环境配置工具，作用域限制在 AI 测试包。
- `frontend/tests/serve_backend.py`：Playwright 的临时后端启动器。

## 运行

以下命令从仓库根目录执行，先用 `uv sync --extra channels` 安装 Python 开发依赖与通知 SDK。后端每条命令使用 60 秒硬超时；完整套件应分组运行，避免进程恢复耗时挤占其他组预算。

```bash
timeout 60s uv run pytest tests --collect-only -q
timeout 60s uv run pytest tests/ai tests/mcp tests/storage_primitives -q
timeout 60s uv run pytest tests/config tests/collection tests/deploy tests/examples -q
timeout 60s uv run pytest tests/channel -q
timeout 60s uv run pytest tests/interaction tests/lifecycle -q
timeout 60s uv run pytest tests/agent -q
for test_file in tests/workflow/test_*.py; do
  if [ "$test_file" = tests/workflow/test_workflow_process_recovery.py ]; then
    continue
  fi
  timeout 60s uv run pytest "$test_file" -q
done
for scenario in during_analysis after_send after_checkpoint_fact_commit in_new_execution_epoch; do
  timeout 60s uv run pytest tests/workflow/test_workflow_process_recovery.py -k "$scenario" -q
done
timeout 60s uv run pytest tests/test_*.py -q
```

单独运行模块或文件时直接指定当前路径，例如 `timeout 60s uv run pytest tests/channel/test_file_channel.py -q`。根目录新增包标记是为了稳定导入，不添加 sys.path 修改或全局夹具。

AI 的普通测试默认使用固定的内存 HTTP 响应，不需要启动模型服务或准备 `.env`。首次运行前需下载真实分词词表：`uv run python -c "import tiktoken; [tiktoken.get_encoding(name) for name in ('cl100k_base', 'o200k_base')]"`，下载后复用本机缓存。`tests/ai/test_live.py` 是单独的真实服务验收，只有设置 `WORKFLOWWEAVE_AI_LIVE=1` 才会运行；真实服务地址和凭据来自 `WORKFLOWWEAVE_AI_ENV` 指定的文件（默认 `.env`）。

需要测试真实模型时单独执行，命令仍受 60 秒硬超时约束：

```bash
env WORKFLOWWEAVE_AI_LIVE=1 timeout 60s uv run pytest tests/ai/test_live.py -q
```

前端在 `frontend/` 执行 `npm test`、`npm run typecheck`；普通浏览器测试先 `npm run build` 再 `npm run test:e2e`（需要 Playwright Chromium）。`npm run test:live` 操作现有前后端服务并创建/清理测试资源，连接要求见对应测试文件顶部与配置。保持测试名和断言语义稳定，目录整理不等于产品行为变更。
