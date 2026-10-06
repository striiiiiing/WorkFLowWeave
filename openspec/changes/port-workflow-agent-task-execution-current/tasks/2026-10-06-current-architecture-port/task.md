# 当前主线架构移植记录

## 决策

`77a3253` 的 Workflow Agent Task 实现作为行为依据，不能直接 cherry-pick：它改动了旧 WorkflowService/旧 graph，并将 MCP 工具替换为 PluginGateway。当前主线已经采用 LangGraph Workflow v4、`WorkflowContext` 依赖注入、原生 SSE 和 MCP schema-first，因此本次只移植产品契约、适配器和测试，不恢复旧运行时。

Agent Task 所有权属于 `WorkflowContext.agent_service` 与 `src/workflowweave/workflow/agent_tasks.py`；节点只选择执行路径，AgentService 继续拥有会话、checkpoint、事件和工具 admission。这样后续 Agent 对话不会写回 Workflow archive。

`agent_mode` 默认关闭以保持兼容；`agent_tools=null` 继承全局启用工具，空列表用于明确隔离；未知工具返回 `tool_unavailable`。模型和 AIConfig 深拷贝到 session 的 invocation 文件，恢复时继续使用冻结配置，显式切换模型才解除冻结。

## 当前状态

当前基线为 `e71341c`；移植行为依据为 `77a3253` 完整代码树，该提交本身仅更新 README。`77a3253` 可从本地备份 ref `backup/main-workflow-before-refactor-20261005-2739c65a` 恢复，无须重新发明已存在实现。

| 合并内容 | 当前落点 | 实施方式 |
| --- | --- | --- |
| Task/FanIn 的 Agent 模式与工具白名单 | `src/workflowweave/models.py`、当前 Workflow 编辑器模块 | 新字段默认关闭；未知工具明确失败 |
| Agent 执行与首轮冻结结果 | `src/workflowweave/workflow/agent_tasks.py` | 恢复历史适配器，接入当前图和 MCP binding |
| 三类会话、冻结模型和 Prompt | `src/workflowweave/agent/service.py` | 扩展现有服务；事件和 checkpoint 仍由 Agent 拥有 |
| 分析/汇总节点与生命周期装配 | `workflow/execution`、`workflow/graph/subgraph`、`lifecycle/service.py` | 保留当前 LangGraph v4 图，注入同一 AgentService |
| 来源接口 | `agent/commands.py`、`interaction/agent_routers.py` | 可选 `task_id` 读取分析/保留 `final` 汇总成功结果 |
| MCP 范围 | `agent/binding.py`、`workflow/storage/sessions.py` | 共用快照投影；运行时输入不依赖开启 Workflow 备份 |
| 编辑、工具选择、报告链接、会话筛选 | `frontend/src/modules/workflows`、`runs`、`agents` | 当前模块目录，不恢复旧 components/views 架构 |
| 无来源 Prompt Workflow | Workflow 模型、collect arrange、来源编辑器 | 显式无来源可继续；已配置但为空的来源仍遵循原策略 |
| 原 OpenSpec change | `workflow-agent-task-execution`、`align-workflow-prompt-contract` | 原样恢复，历史验收不当作当前架构验收 |
| 后端/前端测试 | `tests/agent`、`tests/workflow`、`frontend/tests/unit` | 恢复有意义用例，并适配当前 API/epoch 存档 |

### Prompt 契约范围

本次落实 `align-workflow-prompt-contract` 中与 Agent Task 有关的部分：Task 覆盖优先、Workflow 继承、输入模板单次展开、真实差异作为首轮 Human、保留 Prompt 的恢复/fork、切换模式不填充或清空 Prompt、Agent 汇总使用自身 Prompt 和分析声明顺序。普通 LLM 的单任务消息优化及旧分支资源版本 1→2 迁移属于历史实现，不移入当前资源版本 4；当前 LLM 行为继续以当前主线契约为准。

后续范围补充：用户在移植提交 `3381e04` 后再次明确普通 LLM 单任务优化默认开启、可关闭，Agent 汇总保持三层。普通 LLM 的遗漏项按原有 design 补充实现，详见 [单任务优化修复记录](../../../align-workflow-prompt-contract/tasks/2026-10-06-single-task-optimization/task.md)；旧资源版本迁移仍不属于该补充范围。

### 验证进度

- 适配器、会话和现有 Workflow 定向测试 33 项通过，单进程 60 秒硬超时。
- 变更后端 Ruff、前端类型检查、三个 change 的 OpenSpec strict 已通过。
- 当前图集成、来源 API、无来源 Agent 以及前端最终契约已由主代理修正旧测试后复测通过；后端 13 项、前端 13 项定向用例通过。MCP binding 和 AI Prompt 定向回归另有 12 项通过。
- 最终合并回归在同一进程验证四个新增后端测试文件：42 项全部通过（19.56 秒，60 秒硬超时）；仅有 Starlette/AnyIO 已有弃用警告。
- 当前离线 smoke 另验证混合 LLM/Agent、Agent 汇总、双 Human 首轮 Prompt、MCP binding 冻结和后续对话不改变父 Workflow 版本。
- 测试使用本地脚本模型和 SQLite，不覆盖真实付费模型。
- 用户明确指定 GPT 6 Luna（max）测试子代理；已按此执行初轮核查。后续代理消息被传成密文，子代理无法接收修正要求，因此最终测试修正与复测由主代理完成。MindFS 本地编排 CLI 缺少 `127.0.0.1:7331` token，未创建外部任务组。
