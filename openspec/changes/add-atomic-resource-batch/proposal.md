# 原子批量保存资源

## Why

当 AI 模型配置和引用它的 Workflow 一起调整时，逐项 `save` 会在中间状态触发引用校验，导致本来有效的一组更新无法提交。任务要求明确包含远端 `workflowServer` 的 `save_many` 实现。

## What Changes

- ResourceStore 提供 `save_many`，在同一候选资源视图内校验并原子发布一组更新。
- 生命周期资源存储只在成功发布非空批次后刷新一次定时计划。

## Capabilities

- `resource-storage`：相互依赖的资源可以作为单个事务更新，失败不改变已发布视图或磁盘文件。

## Source

- [任务要求](../backendFix/任务要求.md)
- `ssh myserver:~/opt/workflowServer/src/logagent/config/store.py` 的 `save_many` 语义。
