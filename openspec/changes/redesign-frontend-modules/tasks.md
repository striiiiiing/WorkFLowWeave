# 前端 Model 层重构实施任务

依据：[proposal.md](proposal.md)、[design.md](design.md)、[详细 task](tasks/2026-10-06-frontend-modules/task.md)。只重构 Model；消费层只允许必要导入/类型签名适配，不迁移 API、组件、Composable、页面或路由。

## 1. 基线与模型边界

- [x] 1.1 盘点四个现有 model 目录、DTO/默认值/纯函数和消费者，记录所选交接与实施基线差异；交付类型所有权/路径映射表，以引用扫描验证覆盖。
- [x] 1.2 固定 Model 定向测试、typecheck 和现有消费者契约测试结果；记录 API/UI/Composable/pages 的路径基线，以迁移前后路径比较验证未扩大范围。
- [x] 1.3 在现有架构检查器增加纯 Model 公开出口与 runs → workflows Model 窄依赖规则；用 type-only、动态导入、循环及禁止 API/UI 深层依赖的正反 fixtures 验证。

## 2. Agents Model

- [x] 2.1 将 AgentSession、分支、模型引用、session kind 及来源类型归入 agents/model/session；用字段 round-trip、sessionKind 和类型检查验证原 JSON 形状不变。
- [x] 2.2 将 AgentEvent、ContextBudget、TurnAccepted、工具/设置 DTO、events/transcript/sessionProjection 纯函数归入 agents/model/runtime；用协议、去重、投影和 SDK 消费者测试验证，不移动 stream/adapter 或命令控制器。
- [x] 2.3 将用户 AgentFile/目录/分页/条件写入 DTO 归入 agents/model/workspace，续接输入归 workflow-handoff；用文件契约、ETag 消费者测试和依赖检查验证不包含 Agent 工具执行或第二份 Workflow 正文。

## 3. Resources Model

- [x] 3.1 按 source/mcp/ai/channel 拆类型与 defaults，catalog 聚合 ResourceMap 和唯一 createResource；用四类默认对象对比、MCP 导入和 typecheck 验证不复制 DTO 或改变默认值。
- [x] 3.2 拆 Source definition/call/parameters/overrides 的纯值类型和函数，保持 gateway/save target；用 MCP/CLI 联合类型、静态参数、过滤和编辑保存目标现有测试验证，UI/editor 不搬迁。
- [x] 3.3 盘点 setters 历史字段，只提取真实兼容模型，无实现不造空模块；用声明/导入/API 扫描确认不新增 Setter CRUD、模板管理或后端 resolve 逻辑。

## 4. Workflow Model 聚合

- [x] 4.1 在 workflows/model/create 提取 definition/defaults/actions/validation/backup/sourceUsage/cronPresets，按阶段组合默认值；用 Agent Task、提示词、汇总优化、引用更新及备份 Model 测试验证唯一工厂和不可变动作。
- [x] 4.2 将 runs/model 的 Session/Progress/阶段/终态模型归入 workflows/model/run/shared，恢复请求只移动值类型；用进度、epoch、恢复选项和现有 Run API 契约测试验证，HTTP/SSE 方法保持原位置。
- [x] 4.3 将历史 filters/report/产物可用性模型归入 workflows/model/history，公共 Phase/Session DTO 单一定义；用阶段解析、版本身份、不可用产物和历史筛选测试验证。
- [x] 4.4 更新 runs/api/composables/ui 及其他消费者的 Model 引用和公开出口，删除旧 runs/model/重复定义；用旧路径扫描、纯 Model 架构检查、typecheck 和文件路径基线对比验证消费层只做必要适配。

## 5. 验证与审查

- [x] 5.1 顺序运行 Model 定向单测、typecheck/architecture/受影响格式检查、生产构建和必要消费者回归，记录退出码；只有涉及实际联调时才跑对应 smoke，后端测试每批 60 秒硬超时。
- [x] 5.2 Review diff：只包含 Model、导入/类型适配、公开出口、模型测试和必要依赖规则；核对无重复 DTO/defaults、隐式 fallback 或 API/UI/Composable/路由重构，证据追加详细 task。
- [x] 5.3 执行 openspec validate redesign-frontend-modules --strict --no-interactive，以退出码验证规划/记录；全部实现任务验收后才 archive，文档交付不代表实现完成。
