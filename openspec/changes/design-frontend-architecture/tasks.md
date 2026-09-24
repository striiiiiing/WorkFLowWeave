# 架构设计任务

## 依据与范围

- 用户要求：先设计前端重构架构，后续在另外的 branch 实施。
- [proposal.md](proposal.md) 确定本 change 仅交付文档；[design.md](design.md) 定义候选结构、状态所有权和迁移验收。
- 本次不创建重构分支、不实施业务代码迁移、不修改既有 proposal/design；后续实施另建任务并引用本设计。
- 当前工作区基线是 `main` / `cb01cd6` 加未提交修改，不等同于干净 commit。数据源与 Agent 渠道接入尚需按其所属任务验收。

## 1. 本次设计交付

- [x] 1.1 阅读现有前端设计、后续业务设计/任务及当前代码，记录文档差异和可复用能力。
- [x] 1.2 设计业务模块、允许的依赖方向、跨模块集成及状态唯一拥有者。
- [x] 1.3 定义请求、Schema、Agent SSE/命令、资源编辑和报告读取边界，列出依据及默认值理由。
- [x] 1.4 提供旧文件迁移映射、独立 branch 基线策略、P0–P6 阶段与回退要求。
- [x] 1.5 审查设计内部一致性、相对链接、OpenSpec 严格校验及最终文档差异，记录结果。

## 2. 决策依据摘要

| 决策 | 依据 | 本次处理 |
| --- | --- | --- |
| 结构性重构，保留现有技术栈 | AgentsView、来源组件与续接按钮混合多个职责；现有请求/Schema/测试能力可继续使用 | app/pages/modules/shared；不整站重写 |
| 不恢复 Pinia 全局资源缓存 | 原前端 task 已移除重复 store，当前 package 无 Pinia | 每个页面控制器拥有查询，模块不缓存第二份业务事实 |
| 工作流依赖资源，资源不反向依赖工作流 | sourceUsage 当前位于 resources domain 却使用 WorkflowDefinition | 使用位置计算归 workflows，pages 映射并传入资源 UI |
| Agent 传输与投影分离 | useAgentStream 已实现自有 SSE，add-agent-channels 统一 Web 命令入口 | 保留协议及幂等/终态规则，以注入依赖和纯变换拆分 |
| 不新增请求超时与业务默认值 | 现有模型/前端工厂、轮询 2000ms、SSE 500–5000ms | 在 design §12.2 写明来源，不将无消息视为执行失败 |
| 暂不采用全量 OpenAPI 生成 | 当前动态资源与 SSE 的描述不足以生成完整契约 | 单一 DTO 定义 + 当前后端契约测试 |
| 另立实施 change 和 branch | 用户明确后续另一个 branch；工作区已有大量未提交修改 | 只规划 `refactor/frontend-architecture`，不切换/提交用户工作区 |

## 3. 验证记录

2026-09-24 文档检查已完成：`openspec validate design-frontend-architecture --strict --no-interactive` 通过；相对链接均指向本仓库现有文件；新文档未发现行尾空白。检查 `git status` 时确认工作区已有大量用户未提交修改，本次仅新增/修改本 change 的四个文档文件。此次没有运行前端或后端测试；没有代码修改，架构中的行为要求来自源码与既有设计核对，不是本轮运行验收结论。

## 4. 后续移交

本 change 的完成仅代表草案交付，不代表架构决策已全部获批或重构已实施。后续按 design §11 的 P0 建立可复现基线，在独立分支和新的实施 tasks 中逐批记录验证；不要把本次设计复选框当作实现进度。

## 5. 实施移交（2026-09-24）

用户后续要求依据本设计在独立分支实施，已建立 [refactor-frontend-architecture 实施 change](../refactor-frontend-architecture/proposal.md)；唯一实施清单为 [tasks.md](../refactor-frontend-architecture/tasks.md)。原 proposal/design 保留本次设计阶段的历史内容，不因移交重写。该规划最初交付时等待用户审核；用户随后已明确审核通过并授权继续，且指定全部任务仅在 `/mnt/d/code/LogAgent` 内就地执行，不再使用或新建其他工作目录/worktree。当前 branch `refactor/frontend-architecture` 已接回该目录，按实施 tasks 管理共享文件所有权；后端双向 channel 由另一任务并行重构，本任务只通过每次提交路径审查排除后端，不要求全局 hash 不变。执行路径与协作方式以实施 tasks 的最新记录为准，原 proposal/design 的历史说明不重写。
