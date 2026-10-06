# Model 重构参考与证据

本文件记录来源，不维护第二份任务清单。初稿涉及其他层的设计已按用户最新范围纠正收回。

## 1. 用户与设计依据

| 来源 | 本次采用的约束 |
| --- | --- |
| 用户最新纠正 | 重构 Models；API 在 API 层、组件在组件层；先按业务垂直分层，再在业务 Model 内拆分 |
| 用户前一轮明确要求 | Workspace 给用户操作，Agent 不通过前端操作；Workflow 新建/run/历史模型同文件夹；Resource 独立 |
| [OpenSpec 约定](../../README.md) | 独立 change、纯重构 skip_specs、根 tasks 唯一进度、详细 task 记录依据 |
| [历史前端架构设计](../archive/refactor-frontend-architecture/design.md) | 保留 app/pages/modules/shared 层次、纯 model、公开模块边界和状态唯一拥有者 |

## 2. 本次模型输入

职责依据实施基线 `7ab1429` 的原始模型。以下代码链接已更新到重构后的单一归属；旧路径与新路径映射见 [实施记录](tasks/2026-10-06-frontend-modules/task.md)。

| 文件 | 采用的模型职责 |
| --- | --- |
| [Agent 类型](../../../frontend/src/modules/agents/model/public.ts) | AgentSession、AgentEvent、ContextBudget、AgentFile、AgentTool、AgentConfig/Settings 和 TurnAccepted 应拆分单一所有权 |
| [Agent 事件](../../../frontend/src/modules/agents/model/runtime/events.ts) | 信封校验、终态判断和事件去重是纯模型逻辑 |
| [Agent 会话投影](../../../frontend/src/modules/agents/model/runtime/sessionProjection.ts) | 事件到会话视图的纯转换，仍用同一 AgentSession 定义 |
| [Agent transcript](../../../frontend/src/modules/agents/model/runtime/transcript.ts) | 消息、推理、工具调用展示值投影，不包含 transport |
| [资源类型](../../../frontend/src/modules/resources/model/public.ts) | Source/MCP/AI/Channel、Credential、override/gateway 类型按业务拆分 |
| [资源工厂](../../../frontend/src/modules/resources/model/catalog.ts) | ResourceMap/分类、四种默认对象、名称和凭据 schema 投影，不新增第二工厂 |
| [MCP 配置导入](../../../frontend/src/modules/resources/model/mcp/import.ts) | 归 resources/model/mcp，保持纯解析和现有输入校验 |
| [Workflow 类型](../../../frontend/src/modules/workflows/model/create/definition.ts) | 定义/阶段配置、Agent Task 字段、schedule、backup 归 create |
| [Workflow 默认值](../../../frontend/src/modules/workflows/model/create/defaults.ts) | 阶段 default 提取后由单一 createWorkflow 组合，原值保持 |
| [Workflow 动作](../../../frontend/src/modules/workflows/model/create/actions.ts) | 不可变草稿动作、引用联动归 create，不搬 editor Composable |
| [运行类型](../../../frontend/src/modules/workflows/model/shared/types.ts) | Session/Phase/Progress/Artifact 公共值类型归 workflows/model/shared |
| [运行状态映射](../../../frontend/src/modules/workflows/model/run/session.ts) | Session 状态、阶段和产物标签按 run/history 归属 |
| [运行报告](../../../frontend/src/modules/workflows/model/history/report.ts) | 阶段报告解析和错误/可用性显示归 history |
| [架构检查器](../../../frontend/scripts/check-architecture.mjs) | 扩展纯 Model 公开出口与 runs 消费窄依赖，不新建检查器 |

## 3. 消费层兼容依据

- [所选 Agent 交接](../../../.worktree/redesign-agent-module/docs/redesign-agent-module-handoff.md)：读取检查点 065701c，Agent SDK 已落地但最终验收未完成。主线与交接实现不同，本 change 只迁 Model 并保持所选实现的类型兼容，不合并或迁移 SDK。
- [Source editor](../../../frontend/src/modules/resources/composables/useSourceEditor.ts)：唯一草稿与 gateway 调用保留在 Composable，Model 拆分不重建 state。
- [Workflow editor](../../../frontend/src/modules/workflows/composables/useWorkflowEditor.ts)：草稿拥有者保持原位，defaults/actions 导入更新。
- [Run API](../../../frontend/src/modules/runs/api/runsApi.ts)：API 请求方法保持原位置，可提取其查询/恢复选项值类型到 Workflow Model。
- [Run Session 控制器](../../../frontend/src/modules/runs/composables/useSession.ts)：SSE、版本接纳和 Vue 生命周期不迁入 Model。
- [结果续接页面](../../../frontend/src/pages/integrations/ContinueInAgent.vue)：页面仍组合运行结果与 Agent 创建，模型只表达值类型。

## 4. Setter 边界

[后端调用解析](../../../src/logagent/config/calls.py) 和 [迁移规则](../../../src/logagent/config/migrations.py) 证明旧 Collector/Setter 属于现存历史边界。此 change 不改后端，不恢复前端 Setter CRUD，不把有效调用合并算法复制到 Model。

## 5. 验证范围

规划交付只跑文档/OpenSpec 校验；worktree 实施验证与基线差异记录在 [详细 task](tasks/2026-10-06-frontend-modules/task.md)。实施先跑对应纯 Model 单测，再 typecheck、architecture、build；消费者既有 SDK/资源编辑/运行报告测试用于证明导入适配没有行为变化。无需因文档或目录改名重跑无关后端全量测试。
