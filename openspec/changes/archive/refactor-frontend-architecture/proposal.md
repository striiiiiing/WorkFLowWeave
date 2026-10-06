## Why

用户已要求依据 [前端架构设计](../design-frontend-architecture/design.md) 在独立分支实施重构，先建立任务 DAG，再由指定模型逐包实现和验证。现有页面同时拥有请求、草稿、跨模块操作和展示，导致状态重复、保存范围不清及会话切换竞态；本变更落实已经选定的结构性修复。

## What Changes

- 按已授权设计建立 app/pages/modules/shared，统一 Axios HTTP 工厂、模块 API 注入和 DTO 所有权。
- 分离资源/工作流编辑、运行/报告、系统诊断及 Agent 会话/命令/流/文件的状态与 UI。
- 按工作包维护可并行 DAG、公开接口交接、分批提交与可复现验证，删除迁移完成后的旧实现和过渡出口。
- 将已授权设计中需要明确验收的草稿连续性、保存范围、HTTP 错误和 Agent 会话隔离整理为能力增量；其余既有规范只引用。

## Capabilities

### New Capabilities

无。目录分层本身不建立新的产品能力。

### Modified Capabilities

- `frontend`：补充同屏查询共享、工作流草稿连续性、数据源保存目标及 HTTP 失败语义的可观察验收。
- `agent-interface`：补充 Agent 路由内输入隔离、统一 Web 渠道与未知提交结果的可观察验收。

当前主规范尚未同步这些活动能力，本 change 对此前未形式化的要求使用 ADDED 增量，避免复制旧变更全文或对不存在的主要求执行 MODIFIED。与历史模板入口/旧消息端点的差异在 tasks 中登记，按后续已接受决策验收。

## Impact

代码范围仅 frontend；文档范围为本 change、原设计 tasks 的实施移交链接和前端 README。后端、数据库、服务端协议、密钥及本地运行数据不迁移、不修改。使用 `/mnt/d/code/WorkFLowWeave-frontend-architecture` 的 `refactor/frontend-architecture` 分支，前端基线为 `4e3c524f799edd079356f8c3975632b7968fccbd`。引用式技术设计见 [design.md](design.md)，唯一执行清单见 [tasks.md](tasks.md)。
