# Agent 设计一致性校准记录

## 范围

本记录对应用户要求的最后一轮设计校准。用户已授权连同 `design.md` 一起检查派生文档，但要求保持原设计结构，避免重新通篇审核。本轮只修正与最终设计不一致的表述，不开始产品实现。

## 决策与依据

| 决策 | 依据 | 结果 |
| --- | --- | --- |
| Runtime 使用可读文件入口 | `design.md` §4/§7 的五工具约束和文件优先原则 | 增加只读 `Runtime/Session/<session_id>.json`，包含 session、branch、来源 Workflow、turn、模型和工具 generation；模型仍使用普通 `read`。 |
| Runtime 逻辑路径统一带 `Runtime/` 前缀 | `frontend.md` 的 Runtime 抽屉路径与 `WorkspaceBackend` 映射必须一致 | 将 `Runtime/Session`、`Runtime/Catalog`、`Runtime/Artifacts`、`Runtime/History` 写入映射契约。 |
| 只能整条 thread 清理 | LangGraph `AsyncSqliteSaver` 与 DeltaChannel 的链式 checkpoint 约束，见 `references.md` §2 | 普通 compact/fork 保留中间链；只有过期、无活动、无分支引用、无 Artifact 引用且满足保留策略的整条 thread 才能删除。同步 `proposal.md`。 |

## 验证

- `design.md` 相对基线 `65d600e` 仍保持局部差异；本轮只增加 Runtime 映射和元数据文件说明。
- 派生 spec 已经表达五工具、工作区级锁、压缩排队和整条 thread 清理；未改写历史实施记录中的旧任务事实。
- 完成后运行 OpenSpec strict 校验与 `git diff --check`。
