# 任务

依据：[`workflow-agent-task-execution`](../workflow-agent-task-execution/design.md)、[`align-workflow-prompt-contract`](../align-workflow-prompt-contract/design.md) 和本 change 的设计。

- [x] 1.1 写入当前架构移植 change，记录旧架构不可直接合并的原因。
- [x] 1.2 移植 Task/FanIn Agent 配置、Agent session 元数据和结果 session ID。
- [x] 1.3 接入当前 WorkflowRunner、AgentService、MCP binding 和生命周期组合根。
- [x] 1.4 完成当前架构后端定向测试、恢复/取消/幂等测试。
- [x] 1.5 完成前端类型、构建、OpenSpec strict 和最小集成验证。
- [x] 1.6 接入指定 Task 来源接口、显式无来源 Workflow 和保持原文的 Agent 开关。

## 实施依据

- 当前 Workflow 运行时由 `src/workflowweave/workflow/execution/runner.py` 和 `WorkflowContext` 持有依赖，不能使用旧 `WorkflowService`。
- 当前 Agent 工具入口是 `MCPGateway` 与内置 MCP tool declaration；旧 commit 中的 `PluginGateway` 已被主线 MCP schema-first 设计淘汰。
- `agent_tools=null` 复用全局工具，`[]` 明确禁用工具，依据历史 change 的工具隔离规范。
- 任务首轮默认超时沿用每个冻结 `AIConfig.timeout`，不添加第二个 Workflow 专用超时值。
- 当前运行的 Agent Task 直接使用当前 `WorkflowSnapshot` 的 MCP 范围，通过同一投影函数供运行时和历史来源读取复用，避免关闭 Workflow 配置备份就无法执行 Agent MCP 工具。
- 普通恢复沿用当前 `execution_epoch`；显式重做阶段产生新 epoch 和新 Agent 会话。与旧分支的 attempt/archive key 差异记录在子任务，不更改旧 design。
- 恢复的历史 change 验收记录只代表旧代码树。`align-workflow-prompt-contract` 的普通 LLM 优化/旧资源迁移不移入当前版本 4，详见子任务的合并范围表。

## 验证边界

目标测试使用本地脚本模型和 SQLite，不宣称外部模型或全量回归通过。失败必须保留结构化错误，不能用静默 fallback 掩盖 AgentService 未装配或未知工具。
