# redesign-frontend-modules

前端 **Model 层** 重构规划，尚未 apply。业务顺序为 Agents / Resources / Workflow；再在各业务 model 内划分会话、配置、创建、运行和历史。

API、UI、Composable、页面和路由保持原位置与职责；仅允许模型导入和类型签名适配。初稿扩大到其他层的方案已按用户纠正收回。

- [proposal.md](proposal.md)：范围与影响。
- [design.md](design.md)：Model 目录、依赖图、模型所有权、迁移和验证。
- [references.md](references.md)：用户交接与现有代码证据。
- [tasks.md](tasks.md)：16 项实施与验收任务。
- [详细 task](tasks/2026-10-06-frontend-modules/task.md)：范围纠正、依据、默认值与记录。
