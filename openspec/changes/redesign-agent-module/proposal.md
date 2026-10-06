# 参考 QwenPaw 重设计 Agent 模块

## Why

现有 Agent 的会话管理、轮次执行、模型装配、恢复和事件转换集中在 `service.py`，工具执行事务又混在 `graph.py`；平铺目录不能表达实际的资源所有权和依赖边界。参考邻仓 QwenPaw 的 Builder / Runtime / Executor 分工，重设计 WorkFLowWeave 的内部架构，使后续改动能定位到一个明确的责任模块，并可独立验证。

## What Changes

- 保留 `src/workflowweave/agent/` 作为业务模块，按 LangGraph 运行时、`context`、`tools`、Agent 存储适配、`workspace`、`integrations` 划分内部包；详见 [design.md](design.md#3-源码目录规划)。
- 新增顶层 `src/workflowweave/storage_primitives/`，提供 Agent 与 Workflow 都能使用的原子写入、文件锁、digest、revision/ETag、JSONL 游标和 SQLite 事务辅助；业务事实表、checkpoint 和保留策略仍由各自模块拥有。
- 将 `AgentService` 收敛为用例入口；分离会话事实投影、轮次准入与任务所有权、图构建、执行流转换、恢复协调。
- 将图中的工具副作用执行流程提取为唯一执行器；具体工具、LangChain 适配和存储提交各自分工。
- 将渠道绑定处理归回 `channel`，Agent 命令分发只处理会话用例；与现有 FastAPI 组合根方案对齐。
- 明确源码目录、运行数据目录、逻辑文件目录的区别，保持已有数据路径、checkpoint 格式、事件 ID 和 HTTP/SSE 契约。
- 前端 Agent 页面改用 `@langchain/vue` 的 Composition API；通过自定义 `AgentServerAdapter` 接入现有 WorkFLowWeave API，减少自维护 stream/session 状态，保留现有后端路由语义。
- 记录 QwenPaw 源码依据、LangGraph 运行时边界、存储原语 API、旧文件去向、依赖规则、分阶段实施和行为回归矩阵。设计稿不等于已实现。

## Capabilities

### New Capabilities

无新增用户能力。本文提出内部架构调整，不引入多 Agent、子 Agent、向量记忆、动态 hook 平台或另一套执行框架。

### Modified Capabilities

无业务规范变更。保留 `agent-runtime`、`agent-interface`、`channel`、`workflow-agent-handoff` 等已有约束，来源与测试对应见 [references.md](references.md)。

按照 [OpenSpec 存放约定](../../README.md)，本 change 使用 `skip_specs: true`，不为纯重构制造 ADDED/MODIFIED 业务条款，也不将历史变更增量复制为主规范。若实施需要改变行为、持久化格式或现有设计约束，须先调整设计范围并补充对应能力增量。

## Impact

- 主要代码：`src/workflowweave/agent/`、`src/workflowweave/storage_primitives/`、`frontend/src/modules/agents/`；边界接线：`channel/manager.py`、`channel/agent.py`、FastAPI 组合根及 Agent/Channel 路由、`config/registry.py`、`frontend/package.json`。
- **BREAKING（内部 Python 导入）**：旧内部模块路径随迁移移除，仓内调用方和测试同阶段更新；保留 `workflowweave.agent.AgentService` 作为外部用例入口。HTTP 请求、响应和持久化数据不因此变化。
- 验证：Agent 现有测试、LangGraph checkpoint/interrupt/stream 场景、渠道准入/绑定、交互 SSE、Workflow 交接、存储原语契约、前端 LangChain Vue 测试、生命周期和静态依赖检查。
- 依赖：继续使用现有 LangChain / LangGraph / MCP SDK；前端增加 `@langchain/vue` 与其 peer dependency，版本在实施任务中锁定；不引入 AgentScope 或 QwenPaw 运行依赖。
- 文档：只新增本 change，不改既有 proposal/design 或用户选中的分析文档；前端架构变化已纳入本 change，实施阶段会修改前端模块和依赖。交付范围为规划文档；实现、验收、归档在后续 apply 阶段完成。
