# 规范与变更维护

`specs/<capability>/spec.md` 保存已完成变更中仍有效的行为契约；`changes/<change-id>/` 保存正在实施或验收的增量。规范与实现不一致时记录差距，不从现有代码反向修改已确认要求。

一个变更只维护一份根 `tasks.md`。任务保留可验证的欠账和必要依据，已完成的逐步执行、日期子任务、临时端口和 handoff 通过 Git 历史查阅。`changes/archive/` 仅保留仍有独特价值的提案与设计，不再作为活动状态入口。

## 活动范围

| 变更 | 尚未闭环的范围 |
| --- | --- |
| [文件引用](changes/add-file-reference-collection/tasks.md) | 容器实际读写和重启持久化 |
| [FastAPI 装配与 SSE](changes/centralize-fastapi-lifecycle-sse/tasks.md) | 已撤回实现的重新实施与完整验收 |
| [渠道连接与插件分离](changes/connect-channels-and-separate-builtin-plugins/tasks.md) | 真实首条消息、扫码、回复及通知 |
| [业务压缩评测](changes/evaluate-business-context-compression/tasks.md) | holdout、双 judge、人工标注与费用报告 |
| [Agent 模块](changes/redesign-agent-module/tasks.md) | 跨边界回归、应用 smoke 和所有权审查 |
| [MCP schema-first](changes/redesign-mcp-schema-first/tasks.md) | 原始身份、目录、交接和 Cursor JSON 统一验收；F2 暂缓 |
| [Workflow](changes/redesign-workflow/tasks.md) | 分类期限、清理交接与真实浏览器 SSE |
| [远端部署](changes/remote-workflow-deployment-plugin-compat/tasks.md) | Workflow/SSE、Agent-MCP、成对计量和新服务器业务例子 |
| [前端交互](changes/resolve-remaining-frontend-issues/tasks.md) | 真实浏览器核对续接、模型发现和思考展示 |

微信旧 WeClawBot-API 方案已被 corespeed/wechatbot SDK 取代，旧迁移待办不再保留。Cursor 导入已并入 MCP 变更；示例的新服务器验证并入远端部署。源端 Workflow Agent 与旧资源迁移记录只作历史依据，不能将未移入当前架构的优化或迁移规则发布为现行契约。

新增独立需求按单一目标创建 change；行为变更必须有增量规范，纯内部重构可声明 `skip_specs: true`。归档前分别核对实现与验收证据、主规范基础和增量冲突；文档齐备不代表业务完成。禁止为消除校验错误而将行为变更标为跳过规范。

```bash
openspec list
openspec validate --all --strict --no-interactive
```
