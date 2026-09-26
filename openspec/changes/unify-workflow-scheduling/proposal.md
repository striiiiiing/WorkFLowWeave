# 统一 Workflow 调度

## Why

目前 Workflow 将秒间隔和 Cron 分别保存在 `interval_seconds`、`cron`、`cron_timezone`，`IntervalTrigger` 直接维护两组计划。它无法表达一次性 `at`，且计划存储、CRUD 与计时职责混在一起。用户要求采用 OpenClaw 风格的 `CronStore / CronOps / CronTimer / executeJob` 分层，只用一个定时器管理全部任务。

## What Changes

- Workflow 使用单个 `schedule` 字段表示手动、一次性 `at`、周期性 `every` 或 Cron；移除旧调度字段，并显式迁移已保存的旧资源。
- 调度组件按持久化访问、计划操作、单个 APScheduler 实例和执行入口拆分；所有到期任务仍通过 `WorkflowService.trigger` 运行。
- Cron 使用 `croniter` 计算下一次到期，使用 `cron-descriptor` 生成可读说明。
- 前端编辑器可配置三种调度并展示 Cron 说明。

## Capabilities

- `workflow-schedule`：统一计划配置、可靠的一次性执行、周期调度、时区和可读说明。

## Sources

- [任务要求](../backendFix/任务要求.md)
- 用户后续要求使用 APScheduler 统一管理所有计划。`at/every/cron` 在调度器内分别映射为符合原语义的触发器，不强行改写为五段 Cron 表达式。
- [已有 Cron 设计](../refine-frontend-interactions/design.md)；本变更明确替换其旧间隔兼容决策，依据用户本次回复“迁移为新 schedule 字段并移除旧字段”。
