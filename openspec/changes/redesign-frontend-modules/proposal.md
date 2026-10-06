# 前端 Model 层重构

## Why

当前前端已经按 Agents、Resources、Workflow 划分业务，但各业务 `model/` 内的不同用例和配置类型仍然平铺，Workflow 新建模型与 `runs/model` 的运行和历史模型又分散在两个目录，不利于复用。

本 change 先按业务垂直确定模型所有权，再在业务内部细分 `model/`。用户本轮明确：API 仍在 API 层，组件仍在组件层；本次只重构 Model，不把整套 API、UI 或 Composable 按子域重新搬迁。

## What Changes

- `agents/model/` 内拆为 session、runtime、workspace 和 Workflow 续接输入模型。Workspace 表示用户文件操作；Agent 自己不通过前端操作工作区。
- `resources/model/` 内按 Source、MCP、AI、Channel 拆分，Source 再细分定义、调用、静态参数、Setter 兼容字段和局部覆盖。
- Workflow 新建、运行和历史模型统一到 `workflows/model/{create,run,history}`，共用值类型放在 `workflows/model/shared`。
- 迁移 `runs/model` 到上述 Workflow 模型目录；`runs/api`、`runs/ui`、`runs/composables` 与页面仍保持原位置和职责，只改必要的类型/纯函数引用。
- 保留 Model 公开出口与单一定义；纯模型不导入 Vue、HTTP、SSE 或 UI，不创建新的可变状态容器。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

无。内部 Model 目录和类型所有权重构使用 `skip_specs: true`，不改变用户可观察行为。

## Impact

- 主要范围为 `frontend/src/modules/{agents,resources,workflows,runs}/model/`、对应公开出口和模型测试。
- **BREAKING（内部模型导入）**：旧 model 路径删除时仓内消费者同步更新；API 路径、组件位置、路由、SSE 和后端不变。
- API、Composable、UI 允许修改导入，不拆 API 工厂、不改注入装配、不重构控制器，不移动组件和页面。
- 保留所选交接中的 Agent SDK 模型兼容和 Workflow Agent Task 字段，依据见 [references.md](references.md)。
