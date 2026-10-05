# 当前架构适配设计

## 不变量

1. `agent_mode=false` 与原有 `AIService.execute` 路径一致。
2. 一个 Agent Task 只拥有一个首轮 Agent turn；父 Workflow 取消必须等待 Agent admission 和工具清理。
3. Agent 首轮结果写入 `AnalysisResult`，后续 Agent 对话只写 Agent 自己的事件和 checkpoint。
4. Task 的模型、三层 Prompt 和工具选择在会话创建时冻结；MCP binding 沿用当前 Workflow session snapshot。

## 适配边界

当前 `WorkflowContext` 注入可选 `agent_service`，分析与汇总节点调用统一适配器。适配器只依赖当前 AgentService 的 `create_session/submit/wait/cancel`，不引入旧的 PluginGateway。生命周期组合根先构造 Workflow，再绑定已初始化的 Agent，避免资源装配循环。

## 默认值

- `agent_mode=false`：保持已有 Workflow 配置和运行行为。
- `agent_tools=null`：继承当前 Agent 已启用工具；空数组明确表示不启用工具。
- Agent operation ID 由 Workflow session、execution epoch、阶段和 task ID 派生，保证父图重试不会重复已完成首轮。
- Workflow task 的 input prompt 默认使用现有 `{input}` 模板；继续会话仍保留现有 JSON 输入注入。

## 不在本次范围

父图不恢复 Agent 内部节点；旧 PluginGateway/Collector 不恢复；前端继续使用当前 `frontend/src/modules/*` 模块边界。
